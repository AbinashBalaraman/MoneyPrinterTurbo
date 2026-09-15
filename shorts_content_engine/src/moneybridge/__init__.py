"""Bridge from shorts_content_engine storyboards to MoneyPrinterTurbo.

Money (MoneyPrinterTurbo) assembles final MP4s from a script + materials:
- ``local`` source: our still PNGs + Edge TTS narration (free, works today).
- ``openai_image`` source: our 17 cinematic prompts auto-generated to stills.
"""

from src.moneybridge.adapter import MoneyBridgeAdapter, MoneyTask

__all__ = ["MoneyBridgeAdapter", "MoneyTask"]
