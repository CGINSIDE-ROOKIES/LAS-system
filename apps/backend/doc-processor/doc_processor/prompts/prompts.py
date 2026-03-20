from pathlib import Path

def get_prompts() -> dict[str, str]:
    prompts = dict()
    for f_path in Path(__file__).parent.iterdir():
        if f_path.is_file() and f_path.suffix == ".txt":
            with open(f_path, "r+") as f:
                prompts[f_path.stem] = f.read()
    return prompts
