"""In process registry of paused sandbox sessions for resume and timeout cleanup."""

from app.application.ports.sandbox import SandboxSession


class SandboxRegistry:
    """Tracks live sandbox sessions held open across awaiting_input pauses."""

    def __init__(self) -> None:
        self._sessions: dict[str, SandboxSession] = {}

    def register(self, sandbox_id: str, session: SandboxSession) -> None:
        self._sessions[sandbox_id] = session

    def get(self, sandbox_id: str) -> SandboxSession | None:
        return self._sessions.get(sandbox_id)

    def pop(self, sandbox_id: str) -> SandboxSession | None:
        return self._sessions.pop(sandbox_id, None)

    async def terminate_if_present(self, sandbox_id: str) -> bool:
        session = self._sessions.pop(sandbox_id, None)
        if session is None:
            return False
        await session.terminate()
        return True


_sandbox_registry = SandboxRegistry()


def get_sandbox_registry() -> SandboxRegistry:
    """Return global sandbox session registry."""
    return _sandbox_registry
