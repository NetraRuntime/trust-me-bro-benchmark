"""Minimal Terminus-2 adaptation for official verification after a budget stop."""

from harbor.agents.installed.base import NonZeroAgentExitCodeError
from harbor.agents.terminus_2.terminus_2 import Terminus2
from litellm.exceptions import RateLimitError


class BoundedTerminus2(Terminus2):
    async def run(self, instruction, environment, context):
        try:
            await super().run(instruction, environment, context)
        except RateLimitError as exc:
            # Only the local accounting gate emits 429; upstream HTTP errors
            # are mapped to 502. Harbor still verifies this stopped artifact.
            raise NonZeroAgentExitCodeError("Study accounting gate stopped the agent") from exc
