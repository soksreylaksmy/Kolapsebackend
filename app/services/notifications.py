import httpx

from app.core.config import settings


async def send_telegram(
    text: str,
    chat_id: str,
    reply_markup: dict | None = None,
) -> bool:

    if not settings.telegram_bot_token:
        return False

    if not chat_id:
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{settings.telegram_bot_token}/sendMessage"
    )

    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    # Add Telegram buttons only when provided
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with httpx.AsyncClient(timeout=10) as client:

            response = await client.post(
                url,
                json=payload,
            )

            response.raise_for_status()

        return True

    except httpx.HTTPError as exc:

        print(
            f"Telegram send failed: {exc}"
        )

        return False