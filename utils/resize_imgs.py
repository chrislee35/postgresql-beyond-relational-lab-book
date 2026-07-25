import os
from PIL import Image

# Set the maximum dimension
MAX_SIZE = 600

# Path to your image directory
image_directory = "chapters"

def resize_image_in_place(image_path):
    with Image.open(image_path) as img:
        width, height = img.size

        # Check if resizing is needed
        if width <= MAX_SIZE and height <= MAX_SIZE:
            print(f"Skipping {os.path.basename(image_path)} (already within size limits)")
            return

        # Compute new size while maintaining aspect ratio
        scale = min(MAX_SIZE / width, MAX_SIZE / height)
        new_size = (int(width * scale), int(height * scale))

        # Resize with high-quality resampling
        resized_img = img.resize(new_size, Image.LANCZOS)

        # Save back to the same path
        resized_img.save(image_path, format='PNG', optimize=True)
        print(f"Resized {os.path.basename(image_path)} to {new_size}")

# Walk through all subdirectories
for dirpath, _, filenames in os.walk(image_directory):
    for filename in filenames:
        if filename.lower().endswith(".png"):
            file_path = os.path.join(dirpath, filename)
            resize_image_in_place(file_path)

print("All done!")
