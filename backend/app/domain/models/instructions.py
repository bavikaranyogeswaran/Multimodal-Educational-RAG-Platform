"""Instructions as numbered, classified requirements rather than a paragraph of prose.

A prompt that states what it needs in one long paragraph gives the model no way to tell a
rule from a suggestion, and gives whoever reads the answer afterwards no way to say which
part was not followed. So an instruction here is a thing rather than a sentence: it knows
what kind of instruction it is, how strongly it binds, and — once the set is settled — what
it is called. "The answer ignored R4" is a finding that can be acted on; "the answer did
not follow the instructions" is not.

Conflicts are declared, never inferred. Whether "keep it brief" contradicts "explain each
step fully" is a judgement no rule in this module can make, and guessing at it would drop
instructions nobody asked to drop. Instead an instruction may name the subject it governs,
and two instructions on one subject are treated as competing — which is something their
producer knows and this module does not. An instruction naming no subject competes with
nothing and always survives.

Security rules do not compete; they claim. A security rule naming a subject takes it, and
nothing else naming that subject is sent — not outranked within the prompt, but absent from
it, because a contradiction the model is left to notice is a contradiction that was not
resolved. Two security rules naming one subject both survive, since a contest between them
would have to drop one, and a dropped security rule is the single outcome this module
exists to prevent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import InstructionCategory, RequirementLevel
from app.domain.errors import InvariantViolationError
from app.domain.invariants import require_non_blank, require_timezone_aware


@dataclass(frozen=True, slots=True)
class Instruction:
    """One thing the model is being asked to do, and how much room it has to not do it."""

    text: str
    category: InstructionCategory
    level: RequirementLevel
    subject: str | None = None
    """What this instruction governs — answer length, language, citation style.

    Naming it is how a producer declares that two instructions are about the same thing and
    only one of them can hold. Left unset, the instruction is understood to conflict with
    nothing, which is the safe default: the cost of failing to notice a conflict is a
    prompt that contains both, and the cost of inventing one is a prompt missing something
    the student asked for.
    """

    stated_at: datetime | None = None
    """When the student said it. Absent for the instructions the system always sends, which
    have no moment of origin and are older than anything said in a conversation."""

    is_correction: bool = False
    """Whether this was the student explicitly taking something back."""

    def __post_init__(self) -> None:
        require_non_blank(self.text, "Instruction.text")
        if self.subject is not None:
            require_non_blank(self.subject, "Instruction.subject")
        if self.stated_at is not None:
            require_timezone_aware(self.stated_at, "Instruction.stated_at")
        if self.category.is_security and self.level is not RequirementLevel.CRITICAL:
            raise InvariantViolationError(
                "a security rule must be CRITICAL — one that binds less than critically "
                f"could be outranked by a preference, got {self.level.name}"
            )
        if self.is_correction and self.stated_at is None:
            raise InvariantViolationError(
                "a correction must carry the time it was made — it supersedes by being "
                "more recent, and one with no time cannot be compared against anything"
            )


@dataclass(frozen=True, slots=True)
class NumberedRequirement:
    """An instruction that survived, together with the name it will be referred to by.

    The name is what makes compliance answerable one requirement at a time, both for the
    model asked to follow it and for whatever later asks whether it did.
    """

    identifier: str
    instruction: Instruction

    def __post_init__(self) -> None:
        require_non_blank(self.identifier, "NumberedRequirement.identifier")

    @property
    def rendered(self) -> str:
        """The single line this requirement occupies in a prompt.

        Its name first so a reply can point at it, then how strongly it binds, then what it
        asks. One requirement per line is the whole of what makes this a list rather than a
        paragraph.
        """
        return f"{self.identifier} [{self.instruction.level.name}] {self.instruction.text}"


def resolve_instructions(instructions: Sequence[Instruction]) -> tuple[NumberedRequirement, ...]:
    """Settle the conflicts, put what is left in reading order, and name each one.

    Numbering comes last, after everything that could remove an instruction has run, so the
    names describe what was actually sent rather than what was offered. They are assigned in
    the final reading order, which means the same set of instructions always produces the
    same names — the property that lets a note about R4 still mean something once the prompt
    itself is gone.
    """
    surviving = _drop_the_overridden(instructions)
    ordered = sorted(surviving, key=lambda instruction: instruction.category)
    return tuple(
        NumberedRequirement(identifier=f"R{position}", instruction=instruction)
        for position, instruction in enumerate(ordered, start=1)
    )


def _drop_the_overridden(instructions: Sequence[Instruction]) -> list[Instruction]:
    """Keep every security rule, one instruction per remaining contested subject, and
    everything that named no subject to be contested on."""
    claimed = {
        instruction.subject
        for instruction in instructions
        if instruction.category.is_security and instruction.subject is not None
    }

    # A claimed subject is already settled, and a security rule always names one it has
    # claimed or none at all, so the contest below only ever sees instructions that could
    # actually lose it.
    winners: dict[str, Instruction] = {}
    for instruction in instructions:
        subject = instruction.subject
        if subject is None or subject in claimed:
            continue
        standing = winners.get(subject)
        if standing is None or _standing(instruction) >= _standing(standing):
            winners[subject] = instruction

    return [
        instruction
        for instruction in instructions
        if _survives(instruction, claimed=claimed, winners=winners)
    ]


def _survives(
    instruction: Instruction, *, claimed: set[str], winners: dict[str, Instruction]
) -> bool:
    if instruction.category.is_security or instruction.subject is None:
        return True
    if instruction.subject in claimed:
        return False
    return winners[instruction.subject] is instruction


def _standing(instruction: Instruction) -> tuple[int, float, int]:
    """How well an instruction holds its ground against another one on its subject.

    Level first: a rule outranks a preference wherever the two meet, whenever each was
    said. Then when it was said, because the student's most recent word on a subject is
    their word on it — a correction made this morning does not still bind after they said
    something different this afternoon. Being a correction breaks the remaining ties, which
    is as far as it needs to reach: a correction always carries a time, so against a
    standing preference that carries none it has already won on recency.

    An instruction with no time is older than one that has any. That direction matters: the
    instructions the system always sends carry no time, and they are exactly the ones a
    student should be able to narrow by asking.
    """
    said_at = instruction.stated_at.timestamp() if instruction.stated_at else float("-inf")
    return (instruction.level.value, said_at, int(instruction.is_correction))
