# Why arabic support costs different than English?
## Board Version : We pay AI by word roughly. Some languages cost more. In my experience Arabic is slightly less or as expensive than English in many cases. Hindi costs slighly more.
## Engineer Version: The tokenizer works less efficiently on non latin characters, and the cost may differ based on the language character set. For example, hindi support cost little higher becase the tokens generated is slightly more than the tokens generated for the same sentence in English.
