import os
import re


def redact_ip_addresses(input_file_path):
    """
    Takes a file path, finds all IP addresses, and automatically
    saves a clean copy in the same folder with '_REDACTED' added to the name.
    """

    # 1. Clean up the file path (removes quotes if you used 'Copy as path')
    input_file_path = input_file_path.strip('"').strip("'").strip()

    # 2. Crash Prevention: Verify the file exists
    if not os.path.exists(input_file_path):
        print(f"\n❌ ERROR: Cannot find the file '{input_file_path}'.")
        print("Please check the path and try again.")
        return

    # 3. Auto-generate the output file path next to the original
    # Example: "C:/data/log.txt" becomes "C:/data/log_REDACTED.txt"
    directory, filename = os.path.split(input_file_path)
    name, extension = os.path.splitext(filename)
    output_file_path = os.path.join(directory, f"{name}_REDACTED{extension}")

    # 4. The IP Address Rules
    ipv4_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
    ipv6_pattern = r'\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b'
    ip_regex = re.compile(f'({ipv4_pattern}|{ipv6_pattern})')

    try:
        # 5. Read the original file
        with open(input_file_path, 'r', encoding='utf-8') as file:
            original_text = file.read()

        # 6. Swap the IPs
        clean_text = ip_regex.sub('[REDACTED IP]', original_text)

        # 7. Save the new file
        with open(output_file_path, 'w', encoding='utf-8') as file:
            file.write(clean_text)

        # 8. Success Message
        print(f"\n✅ SUCCESS: File processed securely.")
        print(f"📁 Original: {input_file_path}")
        print(f"📁 Redacted: {output_file_path}\n")

    except Exception as e:
        print(f"\n❌ UNEXPECTED SYSTEM ERROR: {e}\n")


# =================================================================================================================
# INTERACTIVE TERMINAL
# =================================================================================================================
if __name__ == "__main__":
    print("=== IP Redaction Tool ===")
    print("Type 'quit' or 'q' to exit.\n")

    # Loop so you can keep pasting paths without restarting the script
    while True:
        user_path = input("Paste the full file path to clean: ")

        if user_path.lower() in ['quit', 'q', 'exit']:
            print("Exiting tool...")
            break

        if not user_path.strip():
            continue

        redact_ip_addresses(user_path)