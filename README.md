# AI Arena

AI Arena is an interactive debate exhibit with locally hosted AI models and spoken responses.

## Current prototype

`controller/prototype.py` runs a three-round debate between Gemma and Qwen. It streams their responses from Ollama and sends speech chunks to Chatterbox Turbo.

Gemma uses the young, energetic female reference voice in `controller/voices/gemma_energetic_female.wav`. Qwen uses the energetic male reference voice in `controller/voices/qwen_energetic_male.wav`, so the speakers remain easy to distinguish. Both reference clips come from Resemble AI's official Chatterbox Turbo demo: [Gemma's source](https://storage.googleapis.com/chatterbox-demo-samples/turbo/gen_z_female_prompt.wav) and [Qwen's source](https://storage.googleapis.com/chatterbox-demo-samples/turbo/ivr_male_02_prompt.wav).

By default, it expects:

- Gemma: `gemma4:e2b` at `http://192.168.0.186:11434`
- Qwen: `qwen3:4b-instruct` at `http://192.168.0.192:11434`
- The Chatterbox Turbo Python environment and model cache beside this repository

The model names and server addresses can be overridden with `AI_ARENA_GEMMA_MODEL`, `AI_ARENA_QWEN_MODEL`, `AI_ARENA_GEMMA_URL`, and `AI_ARENA_QWEN_URL`.

From the repository directory in PowerShell, run:

```powershell
..\AI-Arena-Chatterbox-env\Scripts\python.exe .\controller\prototype.py
```

The controller checks both Ollama servers before loading speech. This is still a prototype, not the final arena controller.
