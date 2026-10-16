# RAG Generation-Quality Evaluation

Results are descriptive. Structural, retrieval, and semantic measures are separate.

## Structural reliability

| Measure | Value |
| --- | ---: |
| Schema validation | 1.000 |
| Safe failure | 0.000 |
| Retry | 0.083 |
| Controlled repair | 0.896 |

## Retrieval quality

| Measure | Value |
| --- | ---: |
| Diagnostic threshold | 0.300 |
| Hit@1 | 0.000 |
| Hit@5 | 0.000 |
| MRR | 0.000 |

## Semantic generation quality

### Judge: gemini-2.5-flash

#### All (n=48)

| Metric | Scored | Mean (0-1) | Median (0-1) | Score 0 | Score 1 | Score 2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Faithfulness | 48 | 0.802 | 1.000 | 9 | 1 | 38 |
| Answer relevance | 48 | 0.771 | 1.000 | 10 | 2 | 36 |

### Judge: gemini-3.1-pro-preview

#### All (n=48)

| Metric | Scored | Mean (0-1) | Median (0-1) | Score 0 | Score 1 | Score 2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Faithfulness | 48 | 0.688 | 1.000 | 14 | 2 | 32 |
| Answer relevance | 48 | 0.729 | 1.000 | 10 | 6 | 32 |

## Inter-judge agreement

### gemini-2.5-flash vs gemini-3.1-pro-preview (n=48)

| Metric | Exact agreement | Quadratic weighted kappa |
| --- | ---: | ---: |
| Faithfulness | 0.792 | 0.481 |
| Answer relevance | 0.812 | 0.626 |

## Expert validation

PENDING: the blinded 10-case Expert sheet has not been fully scored.

## Representative judge-flagged failures

### Judge: gemini-2.5-flash

#### Faithfulness

| Case | Reason |
| --- | --- |
| rag_val_001 | The explanation invents a general purpose for the system and incorrectly asserts that the requirement aligns with the provided evidence, which is about describing business results, not performing them. |
| rag_val_007 | The explanation claims the requirement lacks a specific measurable transaction rate, but the requirement explicitly states "at least 100 transactions per second". |
| rag_val_013 | The explanation falsely attributes a detailed definition of 'authorized' (including role-based access control, multi-factor authentication, and time-based access restrictions) to ISO 25010:2011. The provided evidence for ISO 25010:2011 only defines 'confidentiality' and mentions 'authorized' without further elaboration. |

#### Answer relevance

| Case | Reason |
| --- | --- |
| rag_val_007 | The rewrite removes the specific transaction rate and replaces it with vague terms, failing to address the stated issue of lacking specificity. It also changes the original intent from throughput to response time. |
| rag_val_008 | The explanation identifies that the evidence does not support the specific time limit in the requirement, but the suggested rewrite is identical to the original requirement and does not address this issue. |
| rag_val_010 | The explanation does not identify a drafting issue in the original requirement. The suggested rewrite introduces a significant change ("excluding caching and temporary data storage") that is not prompted by the explanation and alters the original intent. |

### Judge: gemini-3.1-pro-preview

#### Faithfulness

| Case | Reason |
| --- | --- |
| rag_val_001 | The explanation invents specific business operations and purposes (accurate invoicing) that are not stated in the provided evidence. |
| rag_val_007 | The explanation falsely claims the requirement lacks a specific measurable transaction rate, contradicting the requirement which explicitly specifies 'at least 100 transactions per second'. |
| rag_val_011 | The explanation invents the condition that specific actions or timeframes for account lockout are required to satisfy 'user error protection', which is not supported by the provided evidence. |

#### Answer relevance

| Case | Reason |
| --- | --- |
| rag_val_007 | The rewrite fails to address the issue raised in the explanation (lack of a measurable rate) by introducing vague terms ('reasonable timeframe') and completely abandons the original requirement's intent of 100 transactions per second. |
| rag_val_023 | The suggested rewrite is identical to the original requirement and fails to address the verifiability issue raised in the explanation. |
| rag_val_030 | The suggested rewrite is identical to the original requirement and fails to address the vagueness and lack of metrics described in the explanation. |

## Interpretation boundary

Descriptive only. Version 2 scores only the explanation and suggested rewrite shown to the Expert. The free-form baseline also received retrieved evidence, so these results do not establish improvement over a non-RAG model.
