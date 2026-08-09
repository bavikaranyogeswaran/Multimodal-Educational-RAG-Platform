"""Use case protocol.

Every piece of application behaviour is expressed as a use case: a single public
method that accepts a typed request and returns a typed response. The separation
keeps business logic in the application layer and leaves command/query handlers
independently testable without constructing a full application stack.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

_Req_contra = TypeVar("_Req_contra", contravariant=True)
_Res_co = TypeVar("_Res_co", covariant=True)


class UseCase(Protocol[_Req_contra, _Res_co]):
    """A single unit of application behaviour.

    Implementations live in the commands and queries sub-packages. One typed
    request object in; one typed response out. No positional argument lists; no
    overloaded signatures per calling context.
    """

    async def execute(self, request: _Req_contra) -> _Res_co: ...
