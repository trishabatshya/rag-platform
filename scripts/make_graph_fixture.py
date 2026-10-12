"""Regenerate the authored fictional GraphRAG fixture (no downloaded or generated labels)."""

import json

from app.config import ROOT

# Each tuple deliberately supplies a distinct work, director and birthplace.
BRIDGES = [
    ("Amber Signal", "Mara Vale", "Cedar Bay"),
    ("Silver Orchard", "Elias Reed", "Northhaven"),
    ("Quiet Lantern", "Nadia Frost", "Willowport"),
    ("Winter Atlas", "Owen Pike", "Ashford"),
    ("Copper Horizon", "Leila Moss", "Birch Harbor"),
    ("Hidden Compass", "Jonas Wren", "Fernbridge"),
    ("Velvet River", "Priya Stone", "Maplewick"),
    ("Distant Meadow", "Felix Hart", "Oakmere"),
    ("Morning Beacon", "Sofia Lane", "Pinecrest"),
    ("Blue Meridian", "Amir Wells", "Rosehaven"),
    ("Golden Echo", "Clara Finch", "Elmford"),
    ("Paper Voyage", "Theo Brook", "Juniper Falls"),
]


def build_fixture() -> dict:
    """Return 12 bridge and 3 single-hop questions plus plausible distractors."""
    paragraphs, questions = [], []

    def paragraph(title: str, text: str, source: tuple, relation: str, target: tuple) -> None:
        left, right = dict(zip(("name", "type"), source)), dict(zip(("name", "type"), target))
        paragraphs.append(
            {
                "id": f"{title}::0",
                "title": title,
                "text": text,
                "annotation": {
                    "entities": [left, right],
                    "relations": [
                        {"source": left, "type": relation, "target": right},
                    ],
                },
            }
        )

    for index, (work, person, place) in enumerate(BRIDGES):
        paragraph(
            work,
            f"{person} directed {work}. It is a fictional film about exploration.",
            (person, "PERSON"),
            "DIRECTED",
            (work, "WORK"),
        )
        paragraph(
            person,
            f"{person} was born in {place}. This filmmaker also writes plays.",
            (person, "PERSON"),
            "BORN_IN",
            (place, "PLACE"),
        )
        # Query-like distractors carry a different relationship, not the director's birthplace.
        paragraph(
            f"{work} festival",
            f"{work} festival is located in Seabrook. "
            "The festival discusses where film directors were born.",
            (f"{work} festival", "EVENT"),
            "LOCATED_IN",
            ("Seabrook", "PLACE"),
        )
        questions.append(
            {
                "id": f"bridge-{index + 1:02}",
                "question": f"Where was the director of {work} born?",
                "answer": place,
                "supporting_titles": [work, person],
                "kind": "multihop",
                "steps": [f"Who directed {work}?", "Where was {answer0} born?"],
            }
        )
    for index, (org, city) in enumerate(
        [
            ("Lumen Archive", "Clearwater"),
            ("Cobalt Guild", "Redwood"),
            ("Aurora Library", "Stonehaven"),
        ]
    ):
        paragraph(
            org,
            f"{org} is located in {city}. It preserves fictional local history.",
            (org, "ORG"),
            "LOCATED_IN",
            (city, "PLACE"),
        )
        questions.append(
            {
                "id": f"single-{index + 1}",
                "question": f"Where is {org} located?",
                "answer": city,
                "supporting_titles": [org],
                "kind": "singlehop",
                "steps": [],
            }
        )
    return {
        "description": "Authored fictional facts; annotations for mock extraction only.",
        "paragraphs": paragraphs,
        "questions": questions,
    }


def main() -> None:
    """Write the fixture using portable UTF-8 paths."""
    path = ROOT / "data" / "graph_fixture" / "fixture.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_fixture(), indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
