#!/usr/bin/env python
import sys
import re

# Supported image and file extensions
extensions = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'pdf', 'csv', 'tsv']

# Regex pattern to match Markdown links and images
pattern = re.compile(
    r'(!?)\[(.*?)\]\(([^)]+)\)'
)

def rewrite_link(match):
    is_image = match.group(1) == '!'
    alt_text = match.group(2)
    path = match.group(3)

    # Ignore absolute URLs and internal anchors
    if path.startswith(('http://', 'https://', '#')):
        return match.group(0)

    # Extract filename
    filename = path.split('/')[-1]

    # Check if it's an image or supported file
    ext = filename.split('.')[-1].lower()
    if ext in extensions:
        new_path = f'imgs/{filename}'
    else:
        return match.group(0)

    return f'{match.group(1)}[{alt_text}]({new_path})'

def main():
    input_text = sys.stdin.read()
    output_text = pattern.sub(rewrite_link, input_text)
    print(output_text, end='')

if __name__ == '__main__':
    main()
