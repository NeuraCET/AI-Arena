import os
import time
import warnings
import importlib
import re
from pathlib import Path
from queue import Queue
from threading import Thread


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
MODEL_CACHE = WORKSPACE_ROOT / "AI-Arena-Chatterbox-cache"

os.environ.setdefault("HF_HOME", str(MODEL_CACHE))

warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API.*")
warnings.filterwarnings("ignore", message="`LoRACompatibleLinear` is deprecated.*")

import numpy as np
import sounddevice as sd
import torch
from chatterbox.tts_turbo import ChatterboxTurboTTS
from huggingface_hub import snapshot_download
from tqdm import tqdm as _tqdm


MODEL_ID = "ResembleAI/chatterbox-turbo"
MODEL_FILES = [
    "t3_turbo_v1.safetensors",
    "s3gen_meanflow.safetensors",
    "ve.safetensors",
    "*.json",
    "*.txt",
    "*.pt",
    "*.model",
]
DEFAULT_VOICE = "default"
VOICE_REFERENCES = {
    "gemma_energetic_female": (
        Path(__file__).resolve().parent
        / "voices"
        / "gemma_energetic_female.wav"
    ),
    "qwen_energetic_male": (
        Path(__file__).resolve().parent
        / "voices"
        / "qwen_energetic_male.wav"
    ),
}
SUPPORTED_SPEECH_TAGS = {
    "[sarcastic]",
    "[angry]",
    "[dramatic]",
    "[surprised]",
    "[chuckle]",
    "[laugh]",
    "[groan]",
    "[sigh]",
    "[gasp]",
}
MAX_TAGS_PER_TURN = 2

SILENCE_THRESHOLD = 0.01
LEADING_SILENCE = 0.05
TRAILING_SILENCE = 0.10
CONTINUATION_PAUSE = 0.02
CLAUSE_PAUSE = 0.04
SENTENCE_PAUSE = 0.09

text_queue = Queue()
audio_queue = Queue(maxsize=2)
model = None
voice_conditions = {}
worker_started = False
verbose = os.getenv("AI_ARENA_TTS_VERBOSE", "0") == "1"
tags_queued_this_turn = 0


def _quiet_tqdm(*args, **kwargs):
    kwargs["disable"] = True
    return _tqdm(*args, **kwargs)


# Chatterbox's internal progress bars otherwise overwrite streamed Ollama text.
importlib.import_module("chatterbox.models.t3.t3").tqdm = _quiet_tqdm
flow_matching = importlib.import_module("chatterbox.models.s3gen.flow_matching")
flow_matching.tqdm = _quiet_tqdm
flow_matching.print = lambda *args, **kwargs: None


def _trim_silence(audio):
    audio = np.asarray(audio, dtype=np.float32).flatten()

    if len(audio) == 0:
        return audio

    peak = np.max(np.abs(audio))

    if peak == 0:
        return audio

    active_samples = np.where(np.abs(audio) > peak * SILENCE_THRESHOLD)[0]

    if len(active_samples) == 0:
        return audio

    leading_samples = int(model.sr * LEADING_SILENCE)
    trailing_samples = int(model.sr * TRAILING_SILENCE)
    start = max(0, active_samples[0] - leading_samples)
    end = min(len(audio), active_samples[-1] + trailing_samples + 1)

    return audio[start:end]


def _pause_after(text):
    normalized = text.strip().rstrip("\"'*)]}")

    if normalized.endswith((".", "!", "?")):
        return SENTENCE_PAUSE

    if normalized.endswith((",", ";", ":", "-")):
        return CLAUSE_PAUSE

    return CONTINUATION_PAUSE


def _synthesis_worker():
    while True:
        text, voice = text_queue.get()

        try:
            model.conds = voice_conditions[voice]
            started = time.perf_counter()
            wav = model.generate(
                text,
                cfg_weight=0.0,
                exaggeration=0.0,
                min_p=0.0,
            )
            audio = wav.squeeze().detach().cpu().numpy().astype(np.float32)
            audio = _trim_silence(audio)
            generation_seconds = time.perf_counter() - started

            if verbose:
                print(
                    f"\nChatterbox generated {len(audio) / model.sr:.1f}s of audio "
                    f"in {generation_seconds:.1f}s."
                )

            audio_queue.put((audio, _pause_after(text)))

        except Exception as error:
            print(f"\nChatterbox generation error: {error}")

        finally:
            text_queue.task_done()


def _playback_worker():
    try:
        with sd.OutputStream(
            samplerate=model.sr,
            channels=1,
            dtype="float32",
            latency="low",
        ) as output_stream:
            while True:
                audio, pause = audio_queue.get()

                try:
                    if len(audio) > 0:
                        output_stream.write(audio.reshape(-1, 1))

                    pause_samples = int(model.sr * pause)

                    if pause_samples > 0:
                        silence = np.zeros((pause_samples, 1), dtype=np.float32)
                        output_stream.write(silence)

                except Exception as error:
                    print(f"\nChatterbox playback error: {error}")

                finally:
                    audio_queue.task_done()

    except Exception as error:
        print(f"\nCould not open the audio output: {error}")

        # Keep joins from hanging if the output device cannot be opened.
        while True:
            audio_queue.get()
            audio_queue.task_done()


def load_tts():
    global model, voice_conditions, worker_started

    if model is not None:
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Chatterbox Turbo on {device.upper()}...")

    snapshot_path = snapshot_download(
        repo_id=MODEL_ID,
        cache_dir=MODEL_CACHE,
        allow_patterns=MODEL_FILES,
        local_files_only=True,
    )

    model = ChatterboxTurboTTS.from_local(snapshot_path, device)

    voice_conditions = {DEFAULT_VOICE: model.conds}

    for voice, reference_path in VOICE_REFERENCES.items():
        if not reference_path.is_file():
            raise FileNotFoundError(
                f"Missing reference audio for {voice!r}: {reference_path}"
            )

        print(f"Preparing Chatterbox voice: {voice}...")
        model.prepare_conditionals(str(reference_path))
        voice_conditions[voice] = model.conds

    # Pay the one-time CUDA/kernel startup cost for both debate voices before
    # the live debate begins. The unused built-in fallback stays available.
    for voice in VOICE_REFERENCES:
        model.conds = voice_conditions[voice]
        model.generate(
            "Ready.",
            cfg_weight=0.0,
            exaggeration=0.0,
            min_p=0.0,
        )

    model.conds = voice_conditions[DEFAULT_VOICE]

    if not worker_started:
        Thread(target=_synthesis_worker, daemon=True).start()
        Thread(target=_playback_worker, daemon=True).start()
        worker_started = True

    print("Chatterbox Turbo is ready.")


def queue_text(text, voice=DEFAULT_VOICE):
    global tags_queued_this_turn

    if voice != DEFAULT_VOICE and voice not in VOICE_REFERENCES:
        raise ValueError(f"Unknown Chatterbox voice: {voice!r}")

    # Turbo currently uses its bundled voice.
    def keep_supported_tag(match):
        global tags_queued_this_turn

        tag = match.group(0).lower()

        if tag in SUPPORTED_SPEECH_TAGS and tags_queued_this_turn < MAX_TAGS_PER_TURN:
            tags_queued_this_turn += 1
            return tag

        return ""

    sanitized_text = re.sub(r"\[[^\]]+\]", keep_supported_tag, text)
    sanitized_text = " ".join(sanitized_text.split())

    if sanitized_text:
        text_queue.put((sanitized_text, voice))


def wait_for_speech():
    global tags_queued_this_turn

    text_queue.join()
    audio_queue.join()
    tags_queued_this_turn = 0
