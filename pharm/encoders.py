from functools import lru_cache

import numpy as np

TEXT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
TEXT_REV = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
CLIP_MODEL = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
CLIP_REV = "1a25a446712ba5ee05982a381eed697ef9b435cf"


def model_file(repo, rev, filename):
    from huggingface_hub import hf_hub_download, try_to_load_from_cache
    cached = try_to_load_from_cache(repo, filename, revision=rev)
    return cached if isinstance(cached, str) else hf_hub_download(repo, filename, revision=rev)


def cpu():
    import torch
    torch.set_num_threads(min(4, torch.get_num_threads()))
    return torch


@lru_cache(maxsize=1)
def text_model():
    from pathlib import Path
    from huggingface_hub import snapshot_download
    from sentence_transformers import SentenceTransformer
    cpu()
    try:
        directory = snapshot_download(TEXT_MODEL, revision=TEXT_REV, local_files_only=True)
        if not (Path(directory) / "1_Pooling/config.json").exists():
            raise FileNotFoundError
    except (FileNotFoundError, OSError):
        directory = snapshot_download(TEXT_MODEL, revision=TEXT_REV, allow_patterns=["*.json","*.txt","model.safetensors"])
    return SentenceTransformer(directory, device="cpu")


@lru_cache(maxsize=1)
def visual_model():
    import open_clip
    cpu()
    weights = model_file(CLIP_MODEL, CLIP_REV, "open_clip_model.safetensors")
    model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained=weights,
        image_mean=(0.48145466, 0.4578275, 0.40821073), image_std=(0.26862954, 0.26130258, 0.27577711))
    return model.eval(), preprocess, open_clip.get_tokenizer("ViT-B-32")


def encode_text(sentences):
    return text_model().encode(sentences, normalize_embeddings=True, show_progress_bar=False).astype("float32")


def encode_visual(items, *, images=False):
    torch = cpu()
    model, preprocess, tokenizer = visual_model()
    parts = []
    with torch.inference_mode():
        for offset in range(0, len(items), 8):
            group = items[offset:offset+8]
            if images:
                vectors = model.encode_image(torch.stack([preprocess(img.convert("RGB")) for img in group]))
            else:
                vectors = model.encode_text(tokenizer(group))
            parts.append(torch.nn.functional.normalize(vectors.float(), dim=-1).numpy())
    return np.concatenate(parts)
