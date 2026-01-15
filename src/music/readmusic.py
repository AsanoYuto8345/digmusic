import asyncio
from typing import Optional, Tuple
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager


async def get_current_track():
    """
    現在のメディア情報(winrtのMediaProperties)を返す。
    取れない場合は None。
    """
    try:
        sessions = await MediaManager.request_async()
    except Exception as exc:
        print(f"Failed to access media sessions: {exc}")
        return None

    current = sessions.get_current_session()
    if current is None:
        # print("No active media session found.")
        return None

    try:
        media = await current.try_get_media_properties_async()
    except Exception as exc:
        print(f"Failed to retrieve media info: {exc}")
        return None

    return media


def get_now_playing() -> Optional[Tuple[str, str]]:
    """
    (artist, title) を返す同期関数。
    main_event_logger から直接呼べる形にする。
    """
    media = asyncio.run(get_current_track())
    if media is None:
        return None

    # winrt MediaProperties の代表的な属性
    title = getattr(media, "title", None)
    artist = getattr(media, "artist", None)

    if not title and not artist:
        return None

    return (artist or "Unknown", title or "Unknown")


# 直接実行したときだけ動作確認できるようにする
if __name__ == "__main__":
    print(get_now_playing())
