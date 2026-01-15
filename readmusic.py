import asyncio
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager

async def get_current_track():
    try:
        sessions = await MediaManager.request_async()
    except Exception as exc:
        print(f"Failed to access media sessions: {exc}")
        return None

    current = sessions.get_current_session()
    if current is None:
        print("No active media session found.")
        return None

    try:
        media = await current.try_get_media_properties_async()
    except Exception as exc:
        print(f"Failed to retrieve media info: {exc}")
        return None

    return media

asyncio.run(get_current_track())