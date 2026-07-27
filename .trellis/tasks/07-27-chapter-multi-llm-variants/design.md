# Technical Design

Add a chapter target adapter around the existing chapter prompt/context builder. Candidate output remains separate from `chapters.content`. Adoption writes content/word count/history in one transaction and invalidates frontend project state. Reuse the existing diff component where compatible.
