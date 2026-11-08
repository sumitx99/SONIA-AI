# Hugging Face Spaces vs Render free hosting

Checked: 2026-11-07.

## Verified facts

- Hugging Face Docker Spaces support custom Docker containers, including FastAPI apps. The default exposed app port is 7860.
- Current Hugging Face Spaces docs say compute-backed Gradio and Docker Spaces require a paid plan to create. CPU Basic is listed at no hourly compute cost, but the plan gate still applies. Current PRO price is $9/month and includes hosting ZeroGPU, Gradio, and Docker Spaces.
- CPU Basic hardware is 2 vCPU, 16 GB RAM, and 50 GB non-persistent disk. Free hardware sleeps after inactivity; local disk contents are lost after restarts unless persistence is separately configured.
- Free personal accounts in good standing (verified email, account older than 30 days) can host up to two ZeroGPU Spaces. ZeroGPU is currently Gradio-only, and free-account GPU quota is 5 minutes/day. This is not a general free Docker inference server.
- Render Free web service: 0.1 CPU / 512 MB RAM, spins down after 15 minutes without inbound traffic, wakes in about one minute, and gets 750 instance hours per workspace/month.
- For the SONIA-AI project, `backend/app/services/llm.py` currently configures Gemini as primary and Groq as fallback. Pointing it at a hosted custom model would need backend integration; deploying the model container alone won't switch Sonia to it.

## Official sources

- https://huggingface.co/docs/hub/en/spaces-overview
- https://huggingface.co/docs/hub/en/spaces-sdks-docker
- https://huggingface.co/docs/hub/en/spaces-zerogpu
- https://huggingface.co/pricing
- https://render.com/docs/free
- https://huggingface.co/docs/hub/en/spaces-sdks-docker-first-demo


## Gemini grounding support metadata

For web grounding, the Gemini `GroundingSupport` response object includes `groundingChunkIndices` associated with a claim and a `segment` containing response text. Segment start/end offsets are UTF-8 byte offsets within a part; end is exclusive. For streaming, chunk indices span streamed responses, so clients must accumulate grounding chunks in order.

Official source: https://ai.google.dev/api/generate-content
Grounding with Search guide: https://ai.google.dev/gemini-api/docs/google-search
