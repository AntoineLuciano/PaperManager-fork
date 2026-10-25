"""A fixed research-area taxonomy shared by every conference, and how papers get one.

One taxonomy for all venues makes conferences comparable ("how much of ICML is AI for
science, against NeurIPS?") and keeps an area's colour the same everywhere. Each area
is described by a few short phrases; a paper's area is found zero-shot:

1. prototype = mean embedding of the area's phrases (bge-small, unit length);
2. centre papers and prototypes on the conference's mean paper embedding and assign
   every paper to its nearest prototype. bge vectors share a large common direction
   (median paper-prototype cosine ~0.8, margin ~0.02); without centring the most
   generic area ("efficiency") swallowed a fifth of NeurIPS;
3. twice, move each prototype halfway towards the mean of its papers and reassign,
   so the areas fit the conference's own vocabulary without drifting away from
   their names.

Areas a conference has no papers in are simply absent from its views.
"""
from __future__ import annotations

import numpy as np

AREAS: list[dict] = [
    {"name": "LLM reasoning & test-time compute", "short": "Reasoning", "color": "#9d0208",
     "desc": ["chain-of-thought reasoning in large language models", "mathematical reasoning with LLMs",
              "test-time scaling and inference-time compute for reasoning", "reasoning models trained with reinforcement learning"]},
    {"name": "LLM post-training & alignment", "short": "Post-training", "color": "#d00000",
     "desc": ["RLHF and preference optimization such as DPO", "instruction tuning and supervised fine-tuning of LLMs",
              "reward models for aligning language models", "aligning large language models with human preferences"]},
    {"name": "Efficient models & inference", "short": "Efficiency", "color": "#e85d04",
     "desc": ["quantization and pruning of neural networks", "efficient LLM inference, KV cache and speculative decoding",
              "parameter-efficient fine-tuning with LoRA", "efficient attention, long context and state space models",
              "knowledge distillation and model compression"]},
    {"name": "LLM evaluation & interpretability", "short": "LLM analysis", "color": "#6a040f",
     "desc": ["benchmarks for evaluating large language models", "mechanistic interpretability of transformers",
              "hallucination and factuality of language models", "understanding in-context learning and model behaviour"]},
    {"name": "Agents & tool use", "short": "Agents", "color": "#f48c06",
     "desc": ["LLM agents that use tools", "web and GUI agents", "multi-agent systems of language models",
              "autonomous agents planning with large language models", "code generation and software engineering agents"]},
    {"name": "Language, retrieval & multilinguality", "short": "NLP", "color": "#faa307",
     "desc": ["retrieval-augmented generation", "machine translation and multilingual language models",
              "information extraction, question answering and summarization", "dialogue systems and natural language understanding"]},
    {"name": "Reinforcement learning", "short": "RL", "color": "#e9c46a",
     "desc": ["reinforcement learning algorithms and policy optimization", "offline reinforcement learning",
              "multi-armed bandits and exploration", "model-based reinforcement learning and world models",
              "multi-agent reinforcement learning and game theory"]},
    {"name": "Robotics & embodied AI", "short": "Robotics", "color": "#90be6d",
     "desc": ["robot manipulation and grasping", "vision-language-action models for robots",
              "legged locomotion and robot control", "autonomous driving and motion planning", "embodied navigation"]},
    {"name": "Vision-language & multimodal models", "short": "Multimodal", "color": "#277da1",
     "desc": ["multimodal large language models", "vision-language models and visual question answering",
              "image-text pretraining like CLIP", "video and audio understanding with multimodal LLMs"]},
    {"name": "Image & video generation", "short": "Image/video gen", "color": "#7209b7",
     "desc": ["text-to-image diffusion models", "video generation", "image editing with diffusion models",
              "controllable and personalized image generation", "image restoration and super-resolution"]},
    {"name": "3D vision & reconstruction", "short": "3D vision", "color": "#4d908e",
     "desc": ["3D reconstruction with neural radiance fields and Gaussian splatting", "novel view synthesis",
              "depth estimation, stereo and SLAM", "3D generation of shapes and scenes", "human pose estimation and avatars"]},
    {"name": "Recognition, detection & segmentation", "short": "Recognition", "color": "#43aa8b",
     "desc": ["object detection", "semantic and instance segmentation", "visual tracking", "image classification and recognition",
              "point cloud perception for autonomous driving"]},
    {"name": "Generative modelling (diffusion, flows)", "short": "Gen. models", "color": "#9b5de5",
     "desc": ["diffusion models and score-based generative modelling", "flow matching and normalizing flows",
              "sampling and training theory of diffusion models", "variational autoencoders and energy-based models",
              "discrete diffusion and generative models for text"]},
    {"name": "Representation & self-supervised learning", "short": "Representation", "color": "#4361ee",
     "desc": ["self-supervised and contrastive representation learning", "continual learning and catastrophic forgetting",
              "transfer learning, domain adaptation and generalization", "out-of-distribution detection",
              "foundation model pretraining and scaling laws"]},
    {"name": "Optimization & learning theory", "short": "Theory", "color": "#577590",
     "desc": ["convex and non-convex optimization", "stochastic gradient descent convergence",
              "generalization bounds and statistical learning theory", "theory of deep learning and neural network dynamics",
              "online learning and regret bounds"]},
    {"name": "Probabilistic methods & causality", "short": "Probabilistic", "color": "#3a0ca3",
     "desc": ["Bayesian inference and variational inference", "uncertainty quantification and conformal prediction",
              "causal inference and causal discovery", "Gaussian processes and probabilistic models", "Monte Carlo sampling methods"]},
    {"name": "Safety, security & privacy", "short": "Safety", "color": "#2b2d42",
     "desc": ["adversarial robustness and attacks", "jailbreaking and red-teaming of language models",
              "differential privacy", "federated learning", "backdoor attacks, watermarking and machine unlearning"]},
    {"name": "Fairness, society & human-AI interaction", "short": "Society", "color": "#8d99ae",
     "desc": ["algorithmic fairness and bias", "social impact and ethics of AI", "human-AI interaction and crowdsourcing",
              "AI for education and policy"]},
    {"name": "Graph learning", "short": "Graphs", "color": "#b5838d",
     "desc": ["graph neural networks", "learning on graphs and networks", "knowledge graphs", "combinatorial optimization with graphs"]},
    {"name": "AI for science", "short": "AI4Science", "color": "#2a9d8f",
     "desc": ["machine learning for physics and partial differential equations", "neural operators and scientific simulation",
              "machine learning for chemistry and materials", "weather and climate forecasting with deep learning"]},
    {"name": "Biology & medicine", "short": "Bio & health", "color": "#06d6a0",
     "desc": ["protein structure and design", "molecule generation and drug discovery", "genomics and single-cell biology",
              "medical imaging", "machine learning for healthcare and clinical data"]},
    {"name": "Neuroscience & cognition", "short": "Neuro", "color": "#ef476f",
     "desc": ["computational neuroscience", "brain decoding from neural recordings", "cognitive science and human learning",
              "spiking neural networks and biologically plausible learning"]},
    {"name": "Time series, tabular & data", "short": "Data", "color": "#b08968",
     "desc": ["time series forecasting", "tabular data learning", "recommender systems",
              "datasets and data curation", "anomaly detection"]},
    {"name": "Speech & audio", "short": "Audio", "color": "#ff70a6",
     "desc": ["speech recognition", "text-to-speech synthesis", "music and audio generation", "audio representation learning"]},
]


def prototypes(embed_fn) -> np.ndarray:
    """(areas, dim) unit vectors from the area phrases."""
    rows = []
    for a in AREAS:
        v = np.asarray(embed_fn([f"A research paper about {d}." for d in a["desc"]]), dtype=np.float32)
        m = v.mean(axis=0)
        rows.append(m / (np.linalg.norm(m) + 1e-9))
    return np.stack(rows)


def assign(emb: np.ndarray, protos: np.ndarray, rounds: int = 2) -> np.ndarray:
    """Nearest-prototype labels, refined ``rounds`` times towards the data."""
    if len(emb) == 0:
        return np.zeros(0, dtype=np.int16)
    mu = emb.astype(np.float32).mean(axis=0)
    x = emb.astype(np.float32) - mu
    x /= np.linalg.norm(x, axis=1, keepdims=True) + 1e-9
    protos = protos.astype(np.float32) - mu
    protos /= np.linalg.norm(protos, axis=1, keepdims=True) + 1e-9
    p = protos.copy()
    labels = (x @ p.T).argmax(axis=1)
    for _ in range(rounds):
        for k in range(len(p)):
            members = x[labels == k]
            if len(members) >= 5:
                c = members.mean(axis=0)
                c /= np.linalg.norm(c) + 1e-9
                q = 0.5 * protos[k] + 0.5 * c
                p[k] = q / (np.linalg.norm(q) + 1e-9)
        labels = (x @ p.T).argmax(axis=1)
    return labels.astype(np.int16)


def public() -> list[dict]:
    return [{"name": a["name"], "short": a["short"], "color": a["color"]} for a in AREAS]
