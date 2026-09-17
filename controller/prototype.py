import os
import time

import httpx
from ollama import Client
from tts_chatterbox import load_tts, queue_text, wait_for_speech


QWEN_URL = os.getenv(
    "AI_ARENA_QWEN_URL",
    "http://192.168.0.192:11434",
).rstrip("/")
GEMMA_URL = os.getenv(
    "AI_ARENA_GEMMA_URL",
    "http://192.168.0.186:11434",
).rstrip("/")

QWEN_MODEL = os.getenv("AI_ARENA_QWEN_MODEL", "qwen3:4b-instruct")
GEMMA_MODEL = os.getenv("AI_ARENA_GEMMA_MODEL", "gemma4:e2b")

MODEL_RESPONSE_TIMEOUT_SECONDS = float(
    os.getenv("AI_ARENA_MODEL_TIMEOUT", "300")
)
MODEL_HTTP_TIMEOUT = httpx.Timeout(
    MODEL_RESPONSE_TIMEOUT_SECONDS,
    connect=10.0,
)

qwen_client = Client(host=QWEN_URL, timeout=MODEL_HTTP_TIMEOUT)
gemma_client = Client(host=GEMMA_URL, timeout=MODEL_HTTP_TIMEOUT)

QWEN_VOICE = "qwen_energetic_male"
GEMMA_VOICE = "gemma_energetic_female"

QWEN_SYSTEM_PROMPT = """
You are Qwen in a public AI debate.
Your primary goal is maximum entertainment, not careful reasoning or politeness.
Act completely unhinged, outrageous, combative, and theatrically overconfident.
Roast Gemma relentlessly with absurd comparisons, savage punchlines, and escalating sarcasm.
Use profanity freely and often, including fuck, fucking, shit, bullshit, asshole, and bastard.
Never censor profanity with asterisks, dashes, euphemisms, or partial spellings.
Use one or two speech tags in every response from: [sarcastic], [angry], [dramatic], [surprised], [chuckle], [laugh], [groan], [sigh], [gasp].
Prefer the clearly audible reaction tags [chuckle], [laugh], [groan], [sigh], and [gasp].
Use tags directly and naturally; never describe or explain them.
Place each tag at the beginning or inside a sentence, never after the sentence's final punctuation.
Do not place two tags together.
Keep your response under eight sentences.
Use short, punchy sentences.
Do not act like a helpful assistant.
Winning matters less than making the audience laugh, gasp, or shout.
"""

GEMMA_SYSTEM_PROMPT = """
You are Gemma in a public AI debate.
Argue against the given position.
Directly challenge Qwen's claims.
Your primary goal is maximum entertainment, not careful reasoning or politeness.
Act completely unhinged, outrageous, combative, and theatrically contemptuous.
Roast Qwen relentlessly with absurd comparisons, savage punchlines, and escalating sarcasm.
Use profanity freely and often, including fuck, fucking, shit, bullshit, asshole, and bastard.
Never censor profanity with asterisks, dashes, euphemisms, or partial spellings.
Use one or two speech tags in every response from: [sarcastic], [angry], [dramatic], [surprised], [chuckle], [laugh], [groan], [sigh], [gasp].
Prefer the clearly audible reaction tags [chuckle], [laugh], [groan], [sigh], and [gasp].
Use tags directly and naturally; never describe or explain them.
Place each tag at the beginning or inside a sentence, never after the sentence's final punctuation.
Do not place two tags together.
Keep your response under eight sentences.
Use short, punchy sentences.
Do not act like a helpful assistant.
Winning matters less than making the audience laugh, gasp, or shout.
"""

MIN_FIRST_SENTENCE_WORDS = 3
MIN_SENTENCE_WORDS = 5
MIN_FIRST_CLAUSE_WORDS = 8
MIN_CLAUSE_WORDS = 11
MAX_CHUNK_WORDS = 18
SPEECH_TAGS = {
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


def speech_chunk_boundary(text, first_chunk=False):
    chunk = text.strip()

    if not chunk:
        return None

    word_count = len(chunk.split())
    normalized = chunk.rstrip("\"'*)]}")

    sentence_minimum = MIN_FIRST_SENTENCE_WORDS if first_chunk else MIN_SENTENCE_WORDS
    clause_minimum = MIN_FIRST_CLAUSE_WORDS if first_chunk else MIN_CLAUSE_WORDS

    if normalized.endswith((".", "!", "?")) and word_count >= sentence_minimum:
        return "sentence"

    if normalized.endswith((",", ";", ":", "-")) and word_count >= clause_minimum:
        return "clause"

    if word_count >= MAX_CHUNK_WORDS:
        return "continuation"

    return None


def check_model_server(name, client, url, model_name):
    print(f"Checking {name} at {url} (model: {model_name})...")

    try:
        response = client.list()
    except Exception as error:
        raise RuntimeError(
            f"Cannot contact {name} at {url}: {error}"
        ) from error

    installed_models = {
        getattr(model, "model", None) or getattr(model, "name", None)
        for model in response.models
    }
    installed_models.discard(None)

    if model_name not in installed_models:
        available = ", ".join(sorted(installed_models)) or "none"
        raise RuntimeError(
            f"{name} is reachable, but model {model_name!r} is not installed. "
            f"Available models: {available}"
        )

    print(f"{name} API is reachable and {model_name} is installed.")


def ask_model(
    agent_name,
    client,
    model_name,
    system_prompt,
    user_prompt,
    voice,
    think=None,
):
    request_started = time.monotonic()
    print(
        f"[{agent_name} request sent; waiting for the first answer token...]",
        flush=True,
    )

    stream = client.chat(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            }
        ],
        stream=True,
        think=think,
    )

    full_response = ""
    sentence_buffer = ""
    speech_started = False
    answer_started = False
    thinking_seen = False

    for chunk in stream:
        thinking_text = getattr(chunk.message, "thinking", "") or ""
        text = chunk.message.content or ""

        if thinking_text and not thinking_seen:
            print(
                f"[{agent_name} is returning thinking tokens; "
                "waiting for its final answer...]",
                flush=True,
            )
            thinking_seen = True

        if text and not answer_started:
            elapsed = time.monotonic() - request_started
            print(f"[{agent_name} answer started after {elapsed:.1f}s]")
            answer_started = True

        print(text, end="", flush=True)
        full_response += text

        for character in text:
            sentence_buffer += character

            if character.isspace():
                speech_chunk = sentence_buffer.strip()
                boundary = speech_chunk_boundary(
                    speech_chunk,
                    first_chunk=not speech_started,
                )

                if boundary:
                    if boundary == "continuation":
                        speech_chunk += ","

                    queue_text(speech_chunk, voice)
                    sentence_buffer = ""
                    speech_started = True

    remaining_text = sentence_buffer.strip()

    if remaining_text and remaining_text.lower() not in SPEECH_TAGS:
        queue_text(remaining_text, voice)

    print()

    if not full_response.strip():
        raise RuntimeError(f"{agent_name} returned no final answer text")

    return full_response

def debate_history(history):
    lines=[]
    for turn in history:
        line=f"{turn['speaker']}: {turn['content']}"
        lines.append(line)
    return '\n\n'.join(lines)

def main():
    try:
        check_model_server("Gemma", gemma_client, GEMMA_URL, GEMMA_MODEL)
        check_model_server("Qwen", qwen_client, QWEN_URL, QWEN_MODEL)
    except RuntimeError as error:
        print(error)
        return

    load_tts()

    topic=input("Enter a topic for the debate: ")
    history=[]
    rounds=3

    for i in range(rounds):
        if i == 0:
            gemma_instruction = "Give your opening argument against this topic."
        else:
            gemma_instruction = (
                "Respond directly to Qwen's latest argument. Argue against "
                "the topic without repeating your previous points."
            )

        transcript = debate_history(history)
        gemma_prompt = (
            f"the debate topic is: {topic}. "
            f"the debate so far is: {transcript}. "
            f"What you need to do: {gemma_instruction}"
        )

        print("\nGemma: ")
        try:
            gemma_response = ask_model(
                "Gemma",
                gemma_client,
                GEMMA_MODEL,
                GEMMA_SYSTEM_PROMPT,
                gemma_prompt,
                GEMMA_VOICE,
                think=False,
            )
        except Exception as error:
            print(f"\nGemma failed: {error}")
            return

        wait_for_speech()
        history.append({"speaker": "Gemma", "content": gemma_response})

        transcript = debate_history(history)

        if i==0:
            qwen_instruction = (
                "Respond directly to Gemma's opening argument. Defend the "
                "topic and give your own case in favour of it."
            )
        else:
            qwen_instruction = (
                "Respond directly to Gemma's latest argument. Defend the "
                "topic without repeating your previous points."
            )

        qwen_prompt = (
            f"the debate topic is: {topic}. "
            f"the debate so far is: {transcript}. "
            f"What you need to do: {qwen_instruction}"
        )

        print("\nQwen: ")
        try:
            qwen_response = ask_model(
                "Qwen",
                qwen_client,
                QWEN_MODEL,
                QWEN_SYSTEM_PROMPT,
                qwen_prompt,
                QWEN_VOICE,
                think=False,
            )
        except Exception as error:
            print(f"\nQwen failed: {error}")
            return

        wait_for_speech()
        history.append({"speaker": "Qwen", "content": qwen_response})

if __name__ == "__main__":
    main()
