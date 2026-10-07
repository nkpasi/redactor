import os
from collections import Counter

from presidio_analyzer import AnalyzerEngine, RecognizerResult
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# Load the engines once. This is the slow part (a few seconds).
analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()


def clean_path(raw_path: str) -> str:
    """Removes quotes and spaces that 'Copy as path' adds."""
    return raw_path.strip().strip('"').strip("'").strip()


def build_output_path(input_path: str) -> str:
    """Sample.txt becomes <same folder>/redacted/Sample_REDACTED.txt"""
    folder, filename = os.path.split(input_path)
    name, ext = os.path.splitext(filename)
    return os.path.join(folder, "redacted", f"{name}_REDACTED{ext}")


def choose_types(results: list) -> set:
    """Shows what was found, grouped by type, and asks which types to review."""
    counts = Counter(r.entity_type for r in results)
    print("\nFound these types:")
    for entity_type, count in counts.most_common():
        print(f"  {entity_type}: {count}")

    answer = input(
        "\nType the entity types to review, separated by commas "
        "(or press Enter to review all): "
    ).strip()

    if not answer:
        return set(counts)
    chosen = {item.strip().upper() for item in answer.split(",")}
    return chosen & set(counts)


def review_results(raw_text: str, results: list) -> list:
    """Asks about each flagged item. Returns only the ones you approved."""
    approved = []
    type_decision = {}  # remembers 'all' or 'skip' per entity type

    print("\nControls: y = redact, n = keep, a = redact ALL of this type,")
    print("          s = skip ALL of this type, q = stop and apply what you approved so far")

    for result in results:
        decision = type_decision.get(result.entity_type)
        if decision == "a":
            approved.append(result)
            continue
        if decision == "s":
            continue

        flagged = raw_text[result.start:result.end]
        before = raw_text[max(0, result.start - 40):result.start]
        after = raw_text[result.end:result.end + 40]
        context = f"{before}>>> {flagged} <<<{after}".replace("\n", " ")

        print("\n" + "-" * 50)
        print(f"Type:    {result.entity_type}  (confidence {result.score:.2f})")
        print(f"Found:   {flagged}")
        print(f"Context: ...{context}...")

        while True:
            choice = input("Redact this? (y/n/a/s/q): ").strip().lower()
            if choice in ("y", "n", "a", "s", "q"):
                break
            print("Please type one of: y, n, a, s, q")

        if choice == "q":
            print("Stopping review. Applying approved items so far.")
            break
        if choice in ("y", "a"):
            approved.append(result)
        if choice in ("a", "s"):
            type_decision[result.entity_type] = choice

    return approved


def find_custom_terms(raw_text: str) -> list:
    """Lets you type words the scanner missed. Finds every occurrence."""
    answer = input(
        "\nAnything the scanner missed? Type words or phrases separated by "
        "commas (or press Enter to skip): "
    ).strip()
    if not answer:
        return []

    extra = []
    lowered_text = raw_text.lower()
    for term in [t.strip() for t in answer.split(",") if t.strip()]:
        start = 0
        while True:
            index = lowered_text.find(term.lower(), start)
            if index == -1:
                break
            extra.append(
                RecognizerResult(
                    entity_type="CUSTOM",
                    start=index,
                    end=index + len(term),
                    score=1.0,
                )
            )
            start = index + len(term)
        print(f"  '{term}': added")
    return extra


def redact_file(input_path: str) -> None:
    input_path = clean_path(input_path)

    if not os.path.isfile(input_path):
        print(f"Error: file not found: {input_path}")
        return

    output_path = build_output_path(input_path)

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
    except UnicodeDecodeError:
        print("Error: this is not a plain UTF-8 text file.")
        return

    print(f"\nScanning {os.path.basename(input_path)}...")
    all_results = sorted(analyzer.analyze(text=raw_text, language="en"),
                         key=lambda r: r.start)

    approved = []
    if all_results:
        chosen_types = choose_types(all_results)
        to_review = [r for r in all_results if r.entity_type in chosen_types]
        approved = review_results(raw_text, to_review)
    else:
        print("The scanner found nothing.")

    approved += find_custom_terms(raw_text)

    if not approved:
        print("\nNothing was approved. No file written.")
        return

    # One label per entity type, e.g. [PERSON], [IP_ADDRESS], [CUSTOM]
    operators = {
        entity_type: OperatorConfig("replace", {"new_value": f"[{entity_type}]"})
        for entity_type in {r.entity_type for r in approved}
    }

    safe = anonymizer.anonymize(
        text=raw_text, analyzer_results=approved, operators=operators
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(safe.text)

    print(f"\nDone. {len(approved)} item(s) redacted.")
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    print("=== Interactive Redactor (100% local) ===")
    print("Paste a file path, or type q to quit.\n")
    while True:
        path = input("File path: ")
        if path.strip().lower() in ("q", "quit", "exit"):
            break
        if path.strip():
            redact_file(path)