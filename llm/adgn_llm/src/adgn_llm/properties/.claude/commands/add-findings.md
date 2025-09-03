# Add findings to specimen

@README.md

## What this command does

Add new confirmed findings into a specimen.
If unclear on which specimen you should add to, ask the user to clarify.

Preserve the semantics given to you in the issue descriptions - they may be important for context.
Do not shorten unduly, err on the side of preserving context and explanation of what's wrong and why.

Use checked out source code of the specimen - read code user submits issues on to understand the issues
yourself and submit a good description.

Make sure to properly respect classification into:

- `covered.md` (= issues that are violations of already existing properties - in `definitions/**`),
- `not_covered.md` (= issues that would not clearly fall under already existing properties),
- `false_positives.md` (properties some critique flagged that are not actually problematic).

User may give you a mix. Make sure to properly classify each issue.

**IMPORTANT**: Stick to the **ACTUAL** wording of the definitions **AS THEY EXIST** in `definitions/**.md`.
Do not invent new non-existant properties. Do not stretch definitions beyond what the wording clearly says.
If a finding only tangentially touches on a property but someone just asked "find every place this code
violates this property" would not clearly point it out as "yes, here the property definition is clearly violated",
it does not fall under that property.

## Process

1. Read **ALL** property definition files in `definitions/**.md` to make sure you know the *actual definition wording*.
2. Find if we have the source code of the specimen already checked out. Check specimen `manifest.yaml` and see if there's a `work` subdir under specimen dir.
3. Check if finding submitted by user is already documented; if it is, omit it and tell the user.
4. Add finding to the proper file (`covered/not_covered/false_positives.md`) following guidelines in @README.md.
