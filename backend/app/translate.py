from googletrans import Translator

translator = Translator()

async def translate_text(text: str, target_language: str) -> str:
    try:
        translation = await translator.translate(text, dest=target_language)
        return translation.text
    except Exception as e:
        print(f"Translation error: {e}")
        return text  # Return original text if translation fails