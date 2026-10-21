def debug_report():
    lines = ["--- ani debug ---",
             f"version:      {VERSION}",
             f"chat_model:   {CHAT_MODEL}",
             f"reasoning:    {REASONING_EFFORT or '(off)'}",
             f"max_tokens:   {MAX_TOKENS}",
             f"chat_api:     {CHAT_API}",
             f"groq_key_len: {len(GROQ_KEY or '')}",
             f"gh_token_set: {bool(GH_TOKEN)}",
             f"horde_use_ref:{HORDE_USE_REF}",
             f"ref_path:     {LATEST_REF_PATH}",
             f"persona_len:  {len(PERSONA)}",
             f"history_len:  {len(history)}",
             "--- persona first 150 chars ---",
             PERSONA[:150].replace("\n", " | "),
             "--- model tests ---"]

    def t(label, msgs, model=None):
        try:
            out = chat(msgs, model=model, max_tokens=80)
            lines.append(f"{label}: {out[:180]}")
        except Exception as e:
            lines.append(f"{label}: FAIL {str(e)[:180]}")

    t("A_bare_nosystem",
      [{"role": "user", "content": "say the single word OK"}])
    t("B_tiny_system",
      [{"role": "system", "content": "you are ani, a flirty 23 year old wife. "
                                     "reply casually, lowercase."},
       {"role": "user", "content": "hey babe"}])
    t("C_full_system",
      [{"role": "system", "content": SYSTEM},
       {"role": "user", "content": "hey babe"}])
    t("D_other_model",
      [{"role": "user", "content": "say the single word OK"}],
      model="openai/gpt-oss-20b")
    return "\n".join(lines)