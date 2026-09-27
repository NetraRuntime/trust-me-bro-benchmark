# Threat model

The auditor controls submitted messages, requested controls, endpoint selection and local files. The provider controls weights, hidden instructions, tokenizer, template, serving stack, quantization, caching, routing, metadata and returned text. Aggregators can share upstream providers despite different commercial identities.

A difference can result from decoding, reasoning mode, quantization, batching, hidden instructions, filtering, revisions or software. A non-difference can reflect low power, shared upstreams, selective routing or imitation. Behavioral testing cannot isolate weight substitution without additional controlled evidence.

Public probes are recognizable. Private probes reduce obvious benchmark-specific handling, but do not guarantee adversarial robustness. Providers can route suspected audits to the claimed model, mix models, cache answers or falsify metadata. See [Zhang, Li & Wang (2026)](https://arxiv.org/abs/2606.16100) for spoofing risks; no success rates from that paper are assumed here.

Duplicate response IDs and cache-hit headers flag potentially reused completions. Equal text alone is not evidence of caching: constrained outputs naturally repeat. Cached input prefixes do not imply cached output. Lack of cache signals does not establish independent samples. Correlation and adversarial behavior can violate the exchangeability assumptions of permutation testing.

The largest agreeing cluster is not ground truth. References are user-designated, not certified. Attestation, inspection of weights, supply-chain verification and reference provenance are outside scope.

Treat manifests and provider text as untrusted. Reports escape content; review before publication. Local hashes are identifiers, not signatures: a party controlling a manifest can fabricate evidence. Remote connections require HTTPS and do not follow redirects. HTTP is allowed only on loopback for local endpoints.
