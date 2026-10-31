# Licenses and responsible use

This page is a plain-language orientation, **not legal advice**. The license texts themselves are authoritative.

## What you are allowed to do with H3 Studio's code
MIT: use, copy, modify, publish, sell, keep private. Keep the copyright and license notice. See `LICENSE`.

## The video model is a separate matter
H3 Studio does not contain or distribute any model. When you download MiniMax H3 (or a derivative) and run it in H3cApp, **you accept that model's license**:

* MiniMax H3 Community License Agreement: <https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE>

As of the version reviewed for this project (October 2026) its main points were:

1. **Territory.** The license applies worldwide *except* the European Union, the United Kingdom, South Korea and the United States ("Excluded Territories"). Use, reproduction or display outside the Applicable Territory is not authorised. Check whether you may use the model where you are.
2. **No training other models.** Outputs and the model may not be used to improve any AI model other than MiniMax H3 and its derivatives.
3. **Hosting for others.** If you offer generation to third parties as a product or service, additional obligations (safeguards, notices) apply. H3 Studio is designed as a *private, single-user* tool: it has one shared password and no user accounts. Do not expose it to the public internet.
4. **Acceptable Use Policy.** It forbids, among other things, circumventing safety measures, exploiting minors, impersonation without consent and publishing machine-generated content in public places without clearly disclosing it.
5. **Disclosure.** When you publish generated videos, disclose that they are AI-generated (H3cApp can burn an "AI-generated with MiniMax H3" label and writes a metadata comment; keep it on).
6. **Commercial scale.** Very large commercial use needs separate authorisation from MiniMax.

Community re-quantisations or modified encoders have their own licenses and their own safety trade-offs: read the model card of anything you import.

## H3cApp
MIT-licensed, based on antirez/h3.c. Install it from its own releases page; H3 Studio does not bundle it.

## Your content
Prompts, uploaded images and generated videos stay on your Mac in `data/` (never committed; `.gitignore` excludes it). You are responsible for what you generate and for having the right to use the images you upload.
