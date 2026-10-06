import os
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

# Instantiate engines once at the top
analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()


def process_file(input_filepath: str, output_filepath: str) -> None:
    # Automatically create the destination folder if it doesn't exist
    output_dir = os.path.dirname(output_filepath)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Read the raw, sensitive file
    with open(input_filepath, 'r', encoding='utf-8') as file:
        raw_text = file.read()

    # Run the redaction
    results = analyzer.analyze(text=raw_text, language="en")
    safe_data = anonymizer.anonymize(text=raw_text, analyzer_results=results)

    # Save the safe, redacted version to a new file
    with open(output_filepath, 'w', encoding='utf-8') as file:
        file.write(safe_data.text)  # type: ignore

    print(f"Success! Redacted file saved to: {output_filepath}")


# Usage:
process_file(
    r"C:\Users\npasipamire\Desktop\Projects\Redactor\Sample.txt",
    r"C:\Users\npasipamire\Desktop\Projects\Redactor\redacted\Sample.txt"
)