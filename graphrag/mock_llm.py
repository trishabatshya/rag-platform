"""Deterministic graph completion rules that see prompts and evidence, never gold labels."""

import json
import re


def graph_completion(prompt: str, system: str) -> str:
    """Simulate a planner or short-answer generator from the provided JSON input."""
    data = json.loads(prompt)
    question = data["question"]
    if system == "GRAPH_DECOMPOSE":
        bridge = re.fullmatch(r"Where was the director of (.+) born\?", question)
        steps = [question]
        if bridge:
            steps = [f"Who directed {bridge[1]}?", "Where was {answer0} born?"]
        return json.dumps({"steps": steps})
    text = "\n".join(p["text"] for p in data["paragraphs"])
    directed = re.findall(r"([^\n.]+?) directed ([^.]+)\.", text)
    born = re.findall(r"([^\n.]+?) was born in ([^.]+)\.", text)
    located = re.findall(r"([^\n.]+?) is located in ([^.]+)\.", text)
    who = re.fullmatch(r"Who directed (.+)\?", question)
    bridge = re.fullmatch(r"Where was the director of (.+) born\?", question)
    person_question = re.fullmatch(r"Where was (.+) born\?", question)
    location_question = re.fullmatch(r"Where is (.+) located\?", question)
    if who:
        return next(
            (p.strip() for p, work in directed if work.casefold() == who[1].casefold()),
            "I don't know",
        )
    person = person_question[1] if person_question and not bridge else None
    if bridge:
        person = next(
            (p.strip() for p, work in directed if work.casefold() == bridge[1].casefold()), None
        )
    if person:
        return next(
            (place.strip() for p, place in born if p.strip().casefold() == person.casefold()),
            "I don't know",
        )
    if location_question:
        return next(
            (
                place.strip()
                for org, place in located
                if org.strip().casefold() == location_question[1].casefold()
            ),
            "I don't know",
        )
    return "I don't know"
