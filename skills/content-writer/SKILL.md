---
name: content-writer
description: Generate content in each team member's voice with adaptive voice learning via WhatsApp.
version: 1.2.0
author: GroundUp Toolkit
actions:
  - generate
  - test
---

# Content Writer

WhatsApp-triggered content generation that writes in each team member's authentic voice. Supports LinkedIn posts, Substack notes, LinkedIn messages, and newsletters. Uses per-member voice profiles, audience data, and brand context combined with web research and a humanizer pass.

**Voice Learning**: The system gets smarter over time. Submit writing samples and accept generated content to build an adaptive voice profile that improves with every interaction.

## Content Types

### LinkedIn Post
Short-form content (150-300 words). Direct, insight-driven, observation-first.
Trigger: "write a post about...", "linkedin post about..."

### Substack Note
Ultra-short content (1-10 sentences). Punchy, quotable, single-insight format.
Trigger: "write a note about...", "substack note about..."

### LinkedIn Message
Direct message (2-5 sentences). Warm but direct outreach, no generic templates.
Trigger: "write a message to...", "linkedin message to...", "reach out to..."

### Newsletter / Article
Long-form thought leadership (800-1500 words). Subject line options, sectioned headers, skim-optimized.
Trigger: "write a newsletter about...", "write an article about..."
Delivered via WhatsApp preview + full version by email.

Hebrew messages produce Hebrew output with English tech terms.

## Voice Learning

The system learns your writing style over time through two mechanisms:

### Submit Writing Samples
Send examples of your existing writing to teach the system your voice:
```
voice sample: [paste your post/article/message here]
```
Send at least 2-3 samples for the system to start learning patterns.

### Accept Generated Content
After receiving generated content, reply:
```
keep
```
This saves the content as an accepted voice sample.

### Check Your Voice Profile
```
my voice
```
Shows how many samples you have and when they were last analyzed.

### How It Works
- Samples stored in `profiles/<name>/samples.json` (auto-created)
- When 2+ samples exist, Claude Haiku extracts a style fingerprint
- The fingerprint + up to 2 raw examples are included in every generation prompt
- Max 20 samples per member (oldest pruned, accepted content prioritized)

## Profile Structure

Each team member needs a directory under `profiles/<first_name>/` with:
- `voice.json` — Voice DNA (tone, style, phrases, boundaries)
- `audience.json` — Target audience (pain points, language, aspirations)
- `brand.json` — Business context (positioning, differentiators, offerings)
- `samples.json` — Auto-created when voice samples are submitted

See `profiles/example/` for template files.

## Actions

### generate
```bash
content-writer generate "<message>" "<sender-phone>"
```

### test
```bash
content-writer test
```

## Configuration

Required environment variables:
- `ANTHROPIC_API_KEY` — Claude API for generation + humanizer + voice analysis
- `BRAVE_API_KEY` — Brave Search for topic research (optional but recommended)
