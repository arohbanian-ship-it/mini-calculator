# Mini Calculator user guide

## Normal mode

Enter a calculation and press **Enter**. Previous expressions remain editable. Editing an older expression recalculates its result without silently replacing the text you wrote.

Descriptions and units may stay beside values for later copying into reports. Mathematical operators and parentheses still need to be unambiguous.

Examples:

```text
Area 2.5 m × 4 m
Invoice: 12,500 + 850 delivery
(2+3)/(4+5)
2.(2)
```

## Function buttons

- `Ans` inserts the most recent answer.
- `(x)` inserts empty parentheses, wraps a number only when the cursor is inside it, or wraps a selected range.
- `x^` inserts a power operator or applies it to the selection.
- `x⁻¹` applies a reciprocal.
- `x²` applies a square.
- `√x` applies a square root.
- `π` inserts pi.

## List Mode

Turn on **List Mode** from the right-click menu. Enter one number or operation on each line. Press **Enter** after the last entry to create the result line and a fresh line. While editing a series, its result changes immediately.

`+`, `−`, `×`, and `÷` begin the next operation line. Parentheses may span lines and calculations remain left-to-right except where parentheses explicitly group a part.

An empty line separates completed series. If a new series begins with an operator, Mini Calculator uses the nearest previous series result as its starting value.

## Formatting controls

Right-click the text area or click the `Digits:` indicator to open the settings menu. It contains:

1. Number of fractional digits.
2. **Digit Separator** — comma or apostrophe.
3. **Live Number Formatting**.
4. **Use × and ÷ Symbols**.
5. **List Mode**.
6. **Show Keypad**.

Turning live formatting off removes calculation formatting from existing expressions and answers as well as new input.

Hold **Ctrl** and rotate the mouse wheel to change the font size. Fractional digits use a slightly smaller size automatically.

## Selection, copy, and paste

Select text before pressing a function button to apply the function around that text. Standard copy and paste shortcuts work with English and Persian keyboard layouts. The right-click menu also provides explicit Copy and Paste commands.

## Local data

Mini Calculator stores window geometry, display preferences, the last answer, and calculation history in `calculator_state.txt` beside the program's working location. Close the calculator before copying or deleting this file.
