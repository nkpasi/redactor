import os
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine


def process_file(input_filepath, output_filepath):
    analyzer = AnalyzerEngine()
    anonymizer = AnonymizerEngine()

    # Read the raw, sensitive file
    with open(input_filepath, 'r', encoding='utf-8') as file:
        raw_text = file.read()

    # Run the redaction
    results = analyzer.analyze(text=raw_text, language="en")
    safe_data = anonymizer.anonymize(text=raw_text, analyzer_results=results)

    # Save the safe, redacted version to a new file
    with open(output_filepath, 'w', encoding='utf-8') as file:
        file.write(safe_data.text)

    print(f"Success! Redacted file saved to: {output_filepath}")

# Usage:
process_file("confidential_report.txt", "safe_report_public.txt")