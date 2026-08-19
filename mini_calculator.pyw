import tkinter as tk
import tkinter.font as tkfont
import re
import os
import sys
import ctypes
import math
import ast
import threading

#import pdb
#pdb.set_trace()
from tkinter import messagebox


STATE_FILE = "calculator_state.txt"
DEFAULT_STATE_FILE = "default_calculator_state.txt"
APP_VERSION = "48"
last_result = 0
edited_line_index = None
current_font_size = 16
is_formatting = False   
debounce_id = None
edit_snapshot_text = None
edit_snapshot_taken = False
is_pasting = False
last_key_pressed = ""
last_key_action = ""
MAX_DIGITS=12
RESULT_BOTTOM_SPACING = 4
is_programmatic_edit = False
live_formatting_enabled = True
digit_separator = ","
pretty_operators_enabled = False
list_mode_enabled = False
keypad_visible = True
tray_icon = None
tray_shutdown_event = threading.Event()



try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Per-monitor DPI aware
except Exception:
    pass

# Keywords/functions your calculator supports
ALLOWED_KEYWORDS = ['ans', 'math.sqrt', 'math.pi','e']




#tray icon
def keep_cursor_with_selection():
    """Keep the insertion cursor inside an existing selection, if there is one."""
    try:
        selection_start = calc_text.index("sel.first")
        selection_end = calc_text.index("sel.last")
    except tk.TclError:
        return False

    cursor_is_selected = (
        calc_text.compare("insert", ">=", selection_start)
        and calc_text.compare("insert", "<=", selection_end)
    )
    if not cursor_is_selected:
        calc_text.mark_set("insert", selection_end)

    calc_text.see("insert")
    return True

def restore_selection_cursor_on_focus(event=None):
    """Do not leave a blue selection while the cursor blinks on another line."""
    keep_cursor_with_selection()

def focus_calculator_window():
    root.deiconify()
    root.lift()
    root.focus_force()
    calc_text.focus_set()

    # Preserve a selected range when returning to the calculator. If there is
    # no selection, reopening from the tray still starts on the empty line.
    if not keep_cursor_with_selection():
        calc_text.mark_set("insert", "end-1c")
        calc_text.see("insert")

def show_window(icon=None, item=None):
    root.after(0, focus_calculator_window)

def exit_app(icon=None, item=None):
    if icon is not None:
        icon.stop()
    root.after(0, on_close)



def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def initialize_tray_icon():
    """Load the optional tray components after the calculator is visible."""
    global tray_icon

    try:
        # These are deliberately imported here. Pillow and pystray no longer
        # delay creation of the calculator's main window.
        import pystray
        from PIL import Image

        if tray_shutdown_event.is_set():
            return

        image = Image.open(resource_path("mini_calc.ico"))
        icon = pystray.Icon(
            "Calculator",
            image,
            menu=pystray.Menu(
                pystray.MenuItem(
                    "Show Calculator",
                    show_window,
                    default=True,
                ),
                pystray.MenuItem(
                    "Exit",
                    exit_app,
                ),
            ),
        )
        tray_icon = icon

        if tray_shutdown_event.is_set():
            return

        icon.run()
    except Exception:
        # The calculator itself remains usable if the optional tray icon fails.
        pass


def start_tray_icon():
    """Start tray initialization without blocking the Tkinter event loop."""
    threading.Thread(
        target=initialize_tray_icon,
        name="calculator-tray",
        daemon=True,
    ).start()
    



_drag_start_x = 0
_drag_start_y = 0

def start_window_move(event):
    global _drag_start_x, _drag_start_y
    _drag_start_x = event.x_root
    _drag_start_y = event.y_root

def do_window_move(event):
    global _drag_start_x, _drag_start_y
    dx = event.x_root - _drag_start_x
    dy = event.y_root - _drag_start_y
    x = root.winfo_x() + dx
    y = root.winfo_y() + dy
    root.geometry(f"+{x}+{y}")
    _drag_start_x = event.x_root
    _drag_start_y = event.y_root


def begin_programmatic_edit():
    global is_programmatic_edit
    is_programmatic_edit = True

def end_programmatic_edit():
    global is_programmatic_edit
    is_programmatic_edit = False
    calc_text.edit_modified(False)

def take_edit_snapshot_before_change():
    """Capture history before the first user change to an older line."""
    global edit_snapshot_text, edit_snapshot_taken

    if is_programmatic_edit or edit_snapshot_taken:
        return

    cursor_line = int(calc_text.index("insert").split(".")[0])
    last_line = int(calc_text.index("end-1c").split(".")[0])
    if cursor_line == last_line:
        return

    edit_snapshot_text = calc_text.get("1.0", "end-1c")
    edit_snapshot_taken = True

def strip_keywords(part):
    text=part.lower()
    for kw in ALLOWED_KEYWORDS:
        text = re.sub(rf"\b{re.escape(kw)}\b","",text)
        
        #print(text.strip())
    return text.strip()


def canonicalize_operator_symbols(text):
    """Convert display operators to the symbols used by the evaluator."""
    return str(text).replace("×", "*").replace("÷", "/")


def format_operator_symbols(text, enabled=None):
    """Return text using either keyboard or calculator-style operators."""
    if enabled is None:
        enabled = pretty_operators_enabled

    canonical = canonicalize_operator_symbols(text)
    if enabled:
        return canonical.replace("*", "×").replace("/", "÷")
    return canonical

def is_pure_math(text):
    normalized = canonicalize_operator_symbols(text)
    return bool(re.fullmatch(r"[0-9+\-*/^().,'√²πe]*", normalized))

def is_calculation_part(part):
    """Return True when a whitespace-separated token is used in calculation."""
    stripped = strip_keywords(part)

    # Keep ANS and math.pi even though stripping removes the whole token.
    if not stripped:
        return part.lower() in ("ans", "math.pi")

    return is_pure_math(stripped)

def is_displayed_calculation_part(part):
    """Apply display-only normalizations before classifying a visible token."""
    if part == "=":
        return True

    # The evaluator accepts pi in any case and converts it to the π symbol.
    normalized = re.sub(r"pi", "π", part, flags=re.IGNORECASE)
    return is_calculation_part(normalized)

def get_valid_expression(line_text):
    parts = line_text.strip().split()
    valid_parts = []

    for part in parts:
        if is_calculation_part(part):
            valid_parts.append(canonicalize_operator_symbols(part))

    return " ".join(valid_parts)

def _evaluate_ast_node(node):
    """Evaluate one node from the calculator's restricted expression tree."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("Only numeric constants are allowed")

    if isinstance(node, ast.BinOp):
        left = _evaluate_ast_node(node.left)
        right = _evaluate_ast_node(node.right)

        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Pow):
            return left ** right

        raise ValueError("Unsupported operator")

    if isinstance(node, ast.UnaryOp):
        value = _evaluate_ast_node(node.operand)
        if isinstance(node.op, ast.UAdd):
            return +value
        if isinstance(node.op, ast.USub):
            return -value
        raise ValueError("Unsupported unary operator")

    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "math"
        and node.attr == "pi"
    ):
        return math.pi

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "math"
        and node.func.attr == "sqrt"
        and len(node.args) == 1
        and not node.keywords
    ):
        return math.sqrt(_evaluate_ast_node(node.args[0]))

    raise ValueError(f"Unsupported expression element: {type(node).__name__}")

def safe_evaluate_expression(expression):
    """Parse and calculate an expression without executing arbitrary Python."""
    parsed = ast.parse(expression, mode="eval")
    result = _evaluate_ast_node(parsed.body)
    if isinstance(result, complex):
        raise ValueError("Complex-number results are not supported")
    return result


LIST_OPERATORS = ("**", "+", "-", "*", "/", "^")
GROUPING_SEPARATORS = ",'"
THIN_SPACE = "\u2009"
SPACED_OPERATOR_CHARS = "+-*/×÷="


def strip_digit_separators(text):
    """Remove supported thousands separators from calculation text."""
    return str(text).replace(",", "").replace("'", "")


def is_list_result_text(text):
    """Return True for the result line that closes a List Mode series."""
    return text.strip().startswith("= ")


def is_list_annotation_text(text):
    """Return True for a nonempty List Mode line containing no calculation."""
    stripped = text.strip()
    if not stripped or is_list_result_text(stripped):
        return False
    return not bool(get_valid_expression(stripped))


def prepare_list_operand_expression(expression, answer=0):
    """Normalize one List Mode operand for the restricted evaluator."""
    expr = canonicalize_operator_symbols(
        strip_digit_separators(expression)
    ).strip()
    if not expr:
        raise ValueError("Waiting for number")

    expr = re.sub(
        r'(?<![\d.])0+(\d+)(?![\d.])',
        lambda match: str(int(match.group(0))),
        expr,
    )
    expr = expr.replace("[", "(").replace("]", ")")

    paren_prefix, paren_suffix = get_parenthesis_padding(expr)
    expr = paren_prefix + expr + paren_suffix

    expr = re.sub(r"pi", "π", expr, flags=re.IGNORECASE)
    expr = re.sub(r"(\d|\)|π|\bANS)\(", r"\1*(", expr, flags=re.IGNORECASE)
    expr = re.sub(r"(\d|\)|π|\bANS)√", r"\1*√", expr, flags=re.IGNORECASE)
    expr = re.sub(r"(\d|\)|π|\bANS)π", r"\1*π", expr, flags=re.IGNORECASE)
    expr = re.sub(r"(\d|\)|π|\bANS)(ANS)\b", r"\1*\2", expr, flags=re.IGNORECASE)

    expr = expr.replace("^", "**")
    expr = expr.replace("√(", "math.sqrt(")
    expr = expr.replace("²", "**2")
    expr = expr.replace("π", "math.pi")
    expr = re.sub(r"\bANS\b", str(answer), expr, flags=re.IGNORECASE)
    return expr


def parse_list_entry(line, answer=0):
    """Return the leading operation and numeric value from one list line."""
    math_text = get_valid_expression(strip_digit_separators(line).strip())
    math_text = "".join(math_text.split())
    if not math_text:
        raise ValueError("Waiting for number")

    operation = None
    operand_text = math_text
    for candidate in LIST_OPERATORS:
        if math_text.startswith(candidate):
            operation = "**" if candidate == "^" else candidate
            operand_text = math_text[len(candidate):]
            break

    if not operand_text or operand_text in ("+", "-"):
        raise ValueError("Waiting for number")

    operand_expression = prepare_list_operand_expression(operand_text, answer)
    value = safe_evaluate_expression(operand_expression)
    return operation, value


LIST_NUMBER_TOKEN_PATTERN = re.compile(
    r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?"
)


def build_parenthesized_list_expression(lines):
    """Join List Mode lines while preserving parentheses across line breaks."""
    fragments = []
    contains_parentheses = False

    for line in lines:
        if (
            not line.strip()
            or is_list_result_text(line)
            or is_list_annotation_text(line)
        ):
            continue

        fragment = get_valid_expression(
            strip_digit_separators(line).strip()
        )
        fragment = "".join(fragment.split())
        if not fragment:
            continue

        contains_parentheses = contains_parentheses or "(" in fragment or ")" in fragment
        fragments.append(fragment)

    if not fragments or not contains_parentheses:
        return None

    expression = fragments[0]
    for fragment in fragments[1:]:
        starts_with_operator = (
            fragment.startswith(("+", "-", "*", "/", "^", ")"))
        )
        previous_is_incomplete = expression.endswith(
            ("+", "-", "*", "/", "^", "(", "√")
        )

        # A line without a leading operator is an addition in List Mode,
        # matching the existing top-to-bottom behavior.
        if not starts_with_operator and not previous_is_incomplete:
            expression += "+"
        expression += fragment

    expression = canonicalize_operator_symbols(expression)
    expression = expression.replace("[", "(").replace("]", ")")
    parenthesis_prefix, parenthesis_suffix = get_parenthesis_padding(expression)
    expression = parenthesis_prefix + expression + parenthesis_suffix
    expression = re.sub(r"pi", "π", expression, flags=re.IGNORECASE)
    expression = expression.replace("²", "^(2)")
    return expression


def tokenize_parenthesized_list_expression(expression):
    """Tokenize the calculator's safe numeric syntax and add implicit ×."""
    tokens = []
    index = 0

    while index < len(expression):
        character = expression[index]
        if character.isspace():
            index += 1
            continue

        if expression.startswith("**", index):
            tokens.append("**")
            index += 2
            continue

        number_match = LIST_NUMBER_TOKEN_PATTERN.match(expression, index)
        if number_match:
            tokens.append(number_match.group(0))
            index = number_match.end()
            continue

        ans_match = re.match(r"ANS\b", expression[index:], flags=re.IGNORECASE)
        if ans_match:
            tokens.append("ANS")
            index += len(ans_match.group(0))
            continue

        if character in "+-*/^()√π":
            tokens.append(character)
            index += 1
            continue

        raise ValueError("Unsupported List Mode expression")

    def is_number_token(token):
        return LIST_NUMBER_TOKEN_PATTERN.fullmatch(token) is not None

    with_multiplication = []
    for token in tokens:
        if with_multiplication:
            previous = with_multiplication[-1]
            previous_ends_value = (
                is_number_token(previous)
                or previous in ("ANS", "π", ")")
            )
            token_starts_value = (
                is_number_token(token)
                or token in ("ANS", "π", "(", "√")
            )
            if previous_ends_value and token_starts_value:
                with_multiplication.append("*")
        with_multiplication.append(token)

    return with_multiplication


class ParenthesizedListParser:
    """Evaluate List Mode left-to-right, using parentheses for grouping."""

    OPERATORS = ("+", "-", "*", "/", "^", "**")

    def __init__(self, tokens, answer=0):
        self.tokens = tokens
        self.answer = answer
        self.index = 0

    def parse(self):
        if not self.tokens:
            raise ValueError("Waiting for number")
        value = self.parse_expression()
        if self.index != len(self.tokens):
            raise ValueError("Unsupported List Mode expression")
        return value

    def parse_expression(self):
        value = self.parse_value()

        while self.index < len(self.tokens) and self.tokens[self.index] != ")":
            operator = self.tokens[self.index]
            if operator not in self.OPERATORS:
                raise ValueError("Unsupported List Mode operator")
            self.index += 1
            right = self.parse_value()

            if operator == "+":
                value += right
            elif operator == "-":
                value -= right
            elif operator == "*":
                value *= right
            elif operator == "/":
                value /= right
            else:
                value **= right

        return value

    def parse_value(self):
        if self.index >= len(self.tokens):
            raise ValueError("Waiting for number")

        token = self.tokens[self.index]
        if token in ("+", "-"):
            self.index += 1
            value = self.parse_value()
            return value if token == "+" else -value

        if token == "√":
            self.index += 1
            return math.sqrt(self.parse_value())

        if token == "(":
            self.index += 1
            value = self.parse_expression()
            if self.index >= len(self.tokens) or self.tokens[self.index] != ")":
                raise ValueError("Waiting for closing parenthesis")
            self.index += 1
            return value

        self.index += 1
        if token == "ANS":
            return self.answer
        if token == "π":
            return math.pi
        if LIST_NUMBER_TOKEN_PATTERN.fullmatch(token):
            if "." not in token and "e" not in token.lower():
                return int(token)
            return float(token)

        raise ValueError("Waiting for number")


def evaluate_parenthesized_list_lines(lines, answer=0):
    expression = build_parenthesized_list_expression(lines)
    if expression is None:
        raise ValueError("Waiting for number")
    tokens = tokenize_parenthesized_list_expression(expression)
    return ParenthesizedListParser(tokens, answer).parse()


def evaluate_list_lines(lines, answer=0):
    """Evaluate List Mode entries strictly from top to bottom."""
    parenthesized_expression = build_parenthesized_list_expression(lines)
    if parenthesized_expression is not None:
        tokens = tokenize_parenthesized_list_expression(parenthesized_expression)
        result = ParenthesizedListParser(tokens, answer).parse()
        return normalize_result(result, MAX_DIGITS)

    total = None

    for line in lines:
        if (
            not line.strip()
            or is_list_result_text(line)
            or is_list_annotation_text(line)
        ):
            continue

        operation, value = parse_list_entry(line, answer)

        if total is None:
            if operation in (None, "+"):
                total = value
            elif operation == "-":
                total = -value
            else:
                raise ValueError("The first entry must be a number, +number, or -number")
            continue

        operation = operation or "+"
        if operation == "+":
            total += value
        elif operation == "-":
            total -= value
        elif operation == "*":
            total *= value
        elif operation == "/":
            total /= value
        elif operation == "**":
            total **= value
        else:
            raise ValueError("Unsupported List Mode operator")

    if total is None:
        raise ValueError("Waiting for number")

    return normalize_result(total, MAX_DIGITS)

def is_persian_layout():
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    thread_id = user32.GetWindowThreadProcessId(hwnd, 0)
    hkl = user32.GetKeyboardLayout(thread_id)
    return (hkl & 0xFFFF) == 0x0429  # fa-IR

def normalize_result(value, decimals=MAX_DIGITS):
    """
    Rounds float results to a clean format.
    Keeps integers clean.
    """
    if isinstance(value, float):
        value = round(value, decimals)
        if value.is_integer():
            value = int(value)
    return value

def get_parenthesis_padding(expression):
    """Return the parentheses needed at the start and end of an expression."""
    unmatched_closing = 0
    open_parentheses = 0

    for char in expression:
        if char == "(":
            open_parentheses += 1
        elif char == ")":
            if open_parentheses:
                open_parentheses -= 1
            else:
                unmatched_closing += 1

    return "(" * unmatched_closing, ")" * open_parentheses

def format_number_str(number_str):
    if not number_str:
        return ""

    number_str = strip_digit_separators(number_str)

    #zeroz
    if number_str.startswith(("0", "-0")):
        #print(number_str)
        return number_str

    negative = number_str.startswith('-')
    if negative:
        number_str = number_str[1:]

    if '.' in number_str:
        int_part, frac_part = number_str.split('.', 1)
        if int_part:
            formatted_int = f"{int(int_part):,}".replace(",", digit_separator)
        else:
            formatted_int = ""
        formatted = f"{formatted_int}.{frac_part}"
    else:
        formatted = f"{int(number_str):,}".replace(",", digit_separator)
    return f"-{formatted}" if negative else formatted


def display_number_str(number_str):
    """Return a number using the user's current display-formatting choice."""
    raw_number = strip_digit_separators(number_str)
    if live_formatting_enabled:
        return format_number_str(raw_number)
    return raw_number


GLOBAL_NUMBER_PATTERN = re.compile(
    r"-?(?:\d{1,3}(?:[,']\d{3})+|\d+)(?:\.\d*)?"
)


def transform_number_formatting(text, enabled):
    """Format or unformat every visible number and describe each replacement."""
    replacements = []

    for match in GLOBAL_NUMBER_PATTERN.finditer(text):
        original = match.group(0)
        raw_number = strip_digit_separators(original)

        # Ignore anything that is not a calculator-style decimal number.
        if not re.fullmatch(r"-?\d+(?:\.\d*)?", raw_number):
            continue

        replacement = format_number_str(raw_number) if enabled else raw_number
        if replacement != original:
            replacements.append(
                (match.start(), match.end(), original, replacement)
            )

    if not replacements:
        return text, replacements

    pieces = []
    previous_end = 0
    for start, end, _original, replacement in replacements:
        pieces.append(text[previous_end:start])
        pieces.append(replacement)
        previous_end = end
    pieces.append(text[previous_end:])
    return "".join(pieces), replacements


def map_offset_after_number_formatting(offset, replacements):
    """Keep the cursor/selection beside the same digit after separator changes."""
    shift = 0

    for start, end, original, replacement in replacements:
        if offset <= start:
            break

        if offset >= end:
            shift += len(replacement) - len(original)
            continue

        relative_offset = offset - start
        logical_position = len(
            strip_digit_separators(original[:relative_offset])
        )
        if logical_position == 0:
            return start + shift

        logical_seen = 0
        for replacement_index, character in enumerate(replacement):
            if character not in GROUPING_SEPARATORS:
                logical_seen += 1
            if logical_seen >= logical_position:
                return start + shift + replacement_index + 1

        return start + shift + len(replacement)

    return offset + shift


def reformat_entire_history(enabled):
    """Apply the formatting choice to formulas, results and older lines."""
    global edit_snapshot_text

    original_text = calc_text.get("1.0", "end-1c")
    transformed_text, replacements = transform_number_formatting(
        original_text,
        enabled,
    )

    if edit_snapshot_text is not None:
        edit_snapshot_text, _ = transform_number_formatting(
            edit_snapshot_text,
            enabled,
        )

    if transformed_text == original_text:
        apply_formatting()
        return

    cursor_offset = len(calc_text.get("1.0", "insert"))
    selection_offsets = None
    try:
        selection_offsets = (
            len(calc_text.get("1.0", "sel.first")),
            len(calc_text.get("1.0", "sel.last")),
        )
    except tk.TclError:
        pass

    top_fraction = calc_text.yview()[0]
    new_cursor_offset = map_offset_after_number_formatting(
        cursor_offset,
        replacements,
    )

    begin_programmatic_edit()
    try:
        calc_text.delete("1.0", tk.END)
        calc_text.insert("1.0", transformed_text)
        calc_text.mark_set("insert", f"1.0+{new_cursor_offset}c")

        if selection_offsets is not None:
            new_selection_start = map_offset_after_number_formatting(
                selection_offsets[0],
                replacements,
            )
            new_selection_end = map_offset_after_number_formatting(
                selection_offsets[1],
                replacements,
            )
            calc_text.tag_add(
                tk.SEL,
                f"1.0+{new_selection_start}c",
                f"1.0+{new_selection_end}c",
            )
    finally:
        end_programmatic_edit()

    apply_formatting()
    calc_text.yview_moveto(top_fraction)


def reformat_operator_symbols(enabled):
    """Apply the operator-symbol choice to all visible and saved edit text."""
    global edit_snapshot_text

    original_text = calc_text.get("1.0", "end-1c")
    transformed_text = format_operator_symbols(original_text, enabled)

    if edit_snapshot_text is not None:
        edit_snapshot_text = format_operator_symbols(edit_snapshot_text, enabled)

    if transformed_text == original_text:
        apply_formatting()
        return

    cursor_offset = len(calc_text.get("1.0", "insert"))
    selection_offsets = None
    try:
        selection_offsets = (
            len(calc_text.get("1.0", "sel.first")),
            len(calc_text.get("1.0", "sel.last")),
        )
    except tk.TclError:
        pass

    top_fraction = calc_text.yview()[0]
    begin_programmatic_edit()
    try:
        calc_text.delete("1.0", tk.END)
        calc_text.insert("1.0", transformed_text)
        calc_text.mark_set("insert", f"1.0+{cursor_offset}c")

        if selection_offsets is not None:
            calc_text.tag_add(
                tk.SEL,
                f"1.0+{selection_offsets[0]}c",
                f"1.0+{selection_offsets[1]}c",
            )
    finally:
        end_programmatic_edit()

    apply_formatting()
    calc_text.yview_moveto(top_fraction)


def format_operator_spacing_token(token):
    """Add thin spaces around binary operators in one math token."""
    if not token:
        return token

    result = []
    index = 0
    while index < len(token):
        character = token[index]

        # Keep exponentiation compact: 2**3 (or 2××3 in symbol mode).
        if (
            index + 1 < len(token)
            and canonicalize_operator_symbols(token[index:index + 2]) == "**"
        ):
            previous_significant = next(
                (item for item in reversed(token[:index]) if not item.isspace()),
                None,
            )
            result.extend(token[index:index + 2])
            if previous_significant is None:
                result.append(THIN_SPACE)
            index += 2
            continue

        if character not in SPACED_OPERATOR_CHARS:
            result.append(character)
            index += 1
            continue

        previous_significant = next(
            (item for item in reversed(token[:index]) if not item.isspace()),
            None,
        )
        unary_sign = (
            character in "+-"
            and previous_significant is not None
            and previous_significant in "+-*/×÷^(=√eE"
        )

        if unary_sign:
            result.append(character)
            index += 1
            continue

        if result and not result[-1].isspace():
            result.append(THIN_SPACE)
        result.append(character)
        result.append(THIN_SPACE)
        index += 1

    return "".join(result)


def format_operator_spacing_text(text):
    """Format only calculator tokens, leaving descriptions and units intact."""
    text = str(text).replace(THIN_SPACE, "")
    pieces = re.split(r"(\s+)", text)

    for index, piece in enumerate(pieces):
        if piece and not piece.isspace() and is_displayed_calculation_part(piece):
            pieces[index] = format_operator_spacing_token(piece)

    formatted = "".join(pieces)
    # Do not add a thin space beside a normal user-entered space.
    formatted = re.sub(THIN_SPACE + r"(?=[ \t\r\n])", "", formatted)
    formatted = re.sub(r"(?<=[ \t\r\n])" + THIN_SPACE, "", formatted)
    return formatted


def map_offset_after_operator_spacing(original, transformed, offset):
    """Keep cursor/selection positions stable while thin spaces are changed."""
    logical_offset = len(original[:offset].replace(THIN_SPACE, ""))
    transformed_offset = 0
    logical_seen = 0

    while transformed_offset < len(transformed) and logical_seen < logical_offset:
        if transformed[transformed_offset] != THIN_SPACE:
            logical_seen += 1
        transformed_offset += 1

    # A cursor after an operator belongs after its automatic trailing space.
    while (
        transformed_offset < len(transformed)
        and transformed[transformed_offset] == THIN_SPACE
    ):
        transformed_offset += 1

    return transformed_offset


def reformat_operator_spacing():
    """Apply compact operator spacing to current history and saved edit text."""
    global edit_snapshot_text

    original_text = calc_text.get("1.0", "end-1c")
    transformed_text = format_operator_spacing_text(original_text)

    if edit_snapshot_text is not None:
        edit_snapshot_text = format_operator_spacing_text(edit_snapshot_text)

    if transformed_text == original_text:
        apply_formatting()
        return

    cursor_offset = len(calc_text.get("1.0", "insert"))
    selection_offsets = None
    try:
        selection_offsets = (
            len(calc_text.get("1.0", "sel.first")),
            len(calc_text.get("1.0", "sel.last")),
        )
    except tk.TclError:
        pass

    top_fraction = calc_text.yview()[0]
    begin_programmatic_edit()
    try:
        calc_text.delete("1.0", tk.END)
        calc_text.insert("1.0", transformed_text)
        calc_text.mark_set(
            "insert",
            f"1.0+{map_offset_after_operator_spacing(original_text, transformed_text, cursor_offset)}c",
        )

        if selection_offsets is not None:
            selection_start = map_offset_after_operator_spacing(
                original_text,
                transformed_text,
                selection_offsets[0],
            )
            selection_end = map_offset_after_operator_spacing(
                original_text,
                transformed_text,
                selection_offsets[1],
            )
            calc_text.tag_add(
                tk.SEL,
                f"1.0+{selection_start}c",
                f"1.0+{selection_end}c",
            )
    finally:
        end_programmatic_edit()

    apply_formatting()
    calc_text.yview_moveto(top_fraction)


def format_current_line_operator_spacing():
    """Space the edited line without moving the insertion cursor."""
    line_number, cursor_column = map(
        int,
        calc_text.index("insert").split("."),
    )
    original_line = calc_text.get(
        f"{line_number}.0",
        f"{line_number}.end",
    )
    transformed_line = format_operator_spacing_text(original_line)
    if transformed_line == original_line:
        return

    new_cursor_column = map_offset_after_operator_spacing(
        original_line,
        transformed_line,
        cursor_column,
    )
    begin_programmatic_edit()
    try:
        calc_text.delete(f"{line_number}.0", f"{line_number}.end")
        calc_text.insert(f"{line_number}.0", transformed_line)
        calc_text.mark_set("insert", f"{line_number}.{new_cursor_column}")
    finally:
        end_programmatic_edit()


def insert_spaced_operator(operator):
    """Insert a display operator, then add compact spacing around it."""
    global last_key_pressed

    last_key_pressed = operator
    take_edit_snapshot_before_change()
    try:
        selection_start = calc_text.index("sel.first")
        selection_end = calc_text.index("sel.last")
        calc_text.delete(selection_start, selection_end)
        calc_text.mark_set("insert", selection_start)
    except tk.TclError:
        pass

    displayed_operator = format_operator_symbols(operator)
    calc_text.insert("insert", displayed_operator)
    format_current_line_operator_spacing()
    if live_formatting_enabled:
        apply_number_format()
    apply_formatting()
    if list_mode_enabled:
        calc_text.after_idle(update_list_result_live)
    calc_text.focus_set()

def insert_text(text):
    take_edit_snapshot_before_change()
    calc_text.insert(tk.INSERT, format_operator_symbols(text))
    calc_text.focus_set()


def insert_keypad_operator(operator):
    """Insert an operator while preserving List Mode's line behavior."""
    global last_key_pressed

    last_key_pressed = operator
    take_edit_snapshot_before_change()

    if list_mode_enabled:
        handled = handle_list_operator_key(operator)
        if handled:
            return

    insert_spaced_operator(operator)

def find_number_span_at_cursor(line, cursor_col):
    """Return a number only when the cursor is strictly inside it."""
    number_pattern = re.compile(
        r"(?:\d[\d,']*(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?"
    )

    for match in number_pattern.finditer(line):
        start, end = match.span()

        # Include '-' only when it is a sign, not a subtraction operator.
        if start > 0 and line[start - 1] == "-":
            minus_index = start - 1
            if minus_index == 0 or line[minus_index - 1] in "+-*/×÷^(":
                start = minus_index

        # At either edge, the () button must insert a new empty pair.
        if start < cursor_col < end:
            return start, end

    return None

def wrap_text_in_parentheses(start, end, prefix="", suffix=""):
    """Wrap a Text range, optionally decorating the new parentheses."""
    end_mark = "_parentheses_wrap_end"
    calc_text.mark_set(end_mark, end)
    calc_text.mark_gravity(end_mark, tk.RIGHT)
    calc_text.insert(end, ")" + suffix)
    calc_text.insert(start, prefix + "(")
    calc_text.mark_set("insert", end_mark)
    calc_text.mark_unset(end_mark)
    calc_text.tag_remove(tk.SEL, "1.0", tk.END)
    calc_text.focus_set()


def apply_to_selection_or_insert(prefix, suffix, fallback_text):
    """Decorate a selection as one expression, or use normal insertion."""
    try:
        selection_start = calc_text.index("sel.first")
        selection_end = calc_text.index("sel.last")
    except tk.TclError:
        insert_text(fallback_text)
        return

    take_edit_snapshot_before_change()
    wrap_text_in_parentheses(
        selection_start,
        selection_end,
        prefix=prefix,
        suffix=suffix,
    )

def insert_parentheses():
    take_edit_snapshot_before_change()

    # First priority: wrap the selected text, including multi-line selections.
    try:
        selection_start = calc_text.index("sel.first")
        selection_end = calc_text.index("sel.last")
        wrap_text_in_parentheses(selection_start, selection_end)
        return
    except tk.TclError:
        pass

    # Second priority: wrap the complete number around the insertion cursor.
    pos = calc_text.index(tk.INSERT)
    line_no, cursor_col = map(int, pos.split("."))
    line_text = calc_text.get(f"{line_no}.0", f"{line_no}.end")
    number_span = find_number_span_at_cursor(line_text, cursor_col)

    if number_span:
        number_start, number_end = number_span
        wrap_text_in_parentheses(
            f"{line_no}.{number_start}",
            f"{line_no}.{number_end}"
        )
        return

    # Otherwise insert an empty pair and leave the cursor between them.
    calc_text.insert(pos, "()")
    calc_text.mark_set("insert", f"{pos}+1c")
    calc_text.focus_set()

def insert_power2():
    insert_text("²")

def insert_ans():
    global last_result
    if last_result is None:
        return

    take_edit_snapshot_before_change()
    pos = calc_text.index(tk.INSERT)
    calc_text.insert(pos, "ANS")
    calc_text.mark_set("insert", f"{pos}+3c")
    calc_text.focus()

def format_expression_numbers(line):
    # formats every number in the line
    def repl(match):
        return format_number_str(match.group(0))

    return re.sub(r"-?\d+(\.\d+)?", repl, line)

def ensure_bottom_empty_line():
    # Remove extra empty lines at end
    while True:
        last_line = int(calc_text.index("end-1c").split(".")[0])
        if last_line <= 1:
            break
        if calc_text.get(f"{last_line}.0", f"{last_line}.end").strip() == "" and \
           calc_text.get(f"{last_line-1}.0", f"{last_line-1}.end").strip() == "":
            calc_text.delete(f"{last_line-1}.0", f"{last_line}.0")
        else:
            break

    # Ensure one empty line at bottom
    last_line = int(calc_text.index("end-1c").split(".")[0])
    if calc_text.get(f"{last_line}.0", f"{last_line}.end").strip() != "":
        calc_text.insert("end", "\n")

    calc_text.mark_set("insert", "end-1c")
    calc_text.see("insert")


def get_calculator_lines():
    return calc_text.get("1.0", "end-1c").split("\n")


def find_list_series_bounds(line_no):
    """Find the List Mode block containing (or immediately before) a line."""
    lines = get_calculator_lines()
    if not lines:
        return None

    index = max(0, min(line_no - 1, len(lines) - 1))

    if not lines[index].strip():
        previous_is_entry = (
            index > 0
            and bool(lines[index - 1].strip())
            and not is_list_result_text(lines[index - 1])
        )
        next_is_entry = (
            index + 1 < len(lines)
            and bool(lines[index + 1].strip())
            and not is_list_result_text(lines[index + 1])
        )

        # Preserve compatibility with an unfinished series saved by an older
        # List Mode version that used an empty line before finalization.
        if previous_is_entry:
            index -= 1
        elif next_is_entry:
            index += 1
        else:
            return None

    start = index
    while start > 0:
        previous = lines[start - 1]
        if not previous.strip() or is_list_result_text(previous):
            break
        start -= 1

    end = index
    result_index = index if is_list_result_text(lines[index]) else None
    while result_index is None and end + 1 < len(lines):
        following = lines[end + 1]
        if not following.strip():
            break
        end += 1
        if is_list_result_text(lines[end]):
            result_index = end
            break

    if result_index is not None:
        end = result_index

    return start + 1, end + 1, (result_index + 1 if result_index is not None else None)


def get_list_series_entries(bounds):
    start_line, end_line, result_line = bounds
    final_entry_line = (result_line - 1) if result_line else end_line
    return [
        calc_text.get(f"{line_no}.0", f"{line_no}.end")
        for line_no in range(start_line, final_entry_line + 1)
        if calc_text.get(f"{line_no}.0", f"{line_no}.end").strip()
    ]


def format_list_value(value):
    try:
        return display_number_str(str(normalize_result(value, MAX_DIGITS)))
    except (TypeError, ValueError):
        return str(normalize_result(value, MAX_DIGITS))


def set_list_status(message):
    if "list_status_var" in globals():
        list_status_var.set(message)


def update_list_status(event=None):
    """Show the live result for the series at the insertion cursor."""
    if not list_mode_enabled or "list_status_var" not in globals():
        return

    line_no = int(calc_text.index("insert").split(".")[0])
    bounds = find_list_series_bounds(line_no)
    if not bounds:
        set_list_status("Result: 0")
        return

    entries = get_list_series_entries(bounds)
    if not entries:
        set_list_status("Result: 0")
        return

    calculation_entries = [
        entry for entry in entries if not is_list_annotation_text(entry)
    ]
    if not calculation_entries:
        set_list_status("Result: —")
        return

    try:
        subtotal = evaluate_list_lines(entries, last_result)
        set_list_status(f"Result: {format_list_value(subtotal)}")
    except Exception as error:
        if str(error) == "Waiting for number":
            completed_entries = []
            for entry in entries:
                if is_list_annotation_text(entry):
                    continue
                try:
                    parse_list_entry(entry, last_result)
                except Exception:
                    break
                completed_entries.append(entry)

            if completed_entries:
                try:
                    subtotal = evaluate_list_lines(completed_entries, last_result)
                    set_list_status(
                        f"Result: {format_list_value(subtotal)}  ·  Waiting for number"
                    )
                    return
                except Exception:
                    pass
            set_list_status("Waiting for number")
        else:
            set_list_status("Result unavailable")


def update_list_result_live(event=None):
    """Refresh an existing finalized result without creating text lines."""
    if not list_mode_enabled or is_programmatic_edit:
        return

    cursor_index = calc_text.index("insert")
    line_no = int(cursor_index.split(".")[0])
    line_tags = set(calc_text.tag_names(f"{line_no}.0"))
    if "list_entry" not in line_tags:
        update_list_status()
        return

    bounds = find_list_series_bounds(line_no)
    if not bounds:
        update_list_status()
        return

    _start_line, _end_line, result_line = bounds
    if result_line is None:
        # During entry, the live result belongs only in the fixed status bar.
        # A permanent green result line is created only when Enter is pressed.
        update_list_status()
        return

    entries = get_list_series_entries(bounds)
    try:
        result = evaluate_list_lines(entries, last_result)
    except Exception:
        # While an operator or an incomplete number is being typed, retain the
        # last valid visible result. It will refresh as soon as input is valid.
        update_list_status()
        return

    result_text = f"= {format_list_value(result)}"

    begin_programmatic_edit()
    try:
        current_result = calc_text.get(
            f"{result_line}.0", f"{result_line}.end"
        )
        if current_result != result_text:
            calc_text.delete(f"{result_line}.0", f"{result_line}.end")
            calc_text.insert(f"{result_line}.0", result_text)

        # Updating a result below the edited entry must never pull the cursor
        # away from the number that the user is changing.
        calc_text.mark_set("insert", cursor_index)
    finally:
        end_programmatic_edit()

    apply_formatting()
    calc_text.see("insert")
    update_list_status()


def ensure_list_bottom_input_line():
    """Leave a usable input line without collapsing List Mode separators."""
    begin_programmatic_edit()
    try:
        lines = get_calculator_lines()
        if len(lines) == 1 and not lines[0]:
            calc_text.mark_set("insert", "1.0")
            return

        last_line_no = len(lines)
        last_text = lines[-1]
        if last_text.strip():
            newline_count = 2 if is_list_result_text(last_text) else 1
            calc_text.insert(f"{last_line_no}.end", "\n" * newline_count)
        elif len(lines) >= 2 and is_list_result_text(lines[-2]):
            calc_text.insert("end-1c", "\n")

        calc_text.mark_set("insert", "end-1c")
        calc_text.see("insert")
    finally:
        end_programmatic_edit()


def prepare_new_list_series():
    """Separate newly enabled List Mode from earlier calculator history."""
    begin_programmatic_edit()
    try:
        lines = get_calculator_lines()
        if len(lines) == 1 and not lines[0]:
            calc_text.mark_set("insert", "1.0")
            return

        trailing_empty_lines = 0
        for line in reversed(lines):
            if line.strip():
                break
            trailing_empty_lines += 1

        while trailing_empty_lines < 2:
            calc_text.insert("end-1c", "\n")
            trailing_empty_lines += 1

        calc_text.mark_set("insert", "end-1c")
        calc_text.see("insert")
    finally:
        end_programmatic_edit()


def recalculate_list_series(bounds, create_result=False):
    """Recalculate one series, updating or creating only its result line."""
    global last_result, edit_snapshot_text, edit_snapshot_taken

    start_line, end_line, result_line = bounds
    entries = get_list_series_entries(bounds)
    try:
        result = evaluate_list_lines(entries, last_result)
    except Exception as error:
        if str(error) == "Waiting for number":
            set_list_status("Waiting for number")
        else:
            set_list_status("Result unavailable")
        return False

    result = normalize_result(result, MAX_DIGITS)
    result_text = f"= {format_list_value(result)}"

    begin_programmatic_edit()
    try:
        if result_line is not None:
            calc_text.delete(f"{result_line}.0", f"{result_line}.end")
            calc_text.insert(f"{result_line}.0", result_text)
        elif create_result:
            insertion_line = end_line + 1
            total_lines = int(calc_text.index("end-1c").split(".")[0])
            if (
                insertion_line <= total_lines
                and not calc_text.get(
                    f"{insertion_line}.0", f"{insertion_line}.end"
                ).strip()
            ):
                calc_text.insert(f"{insertion_line}.0", result_text)
                result_line = insertion_line
            else:
                calc_text.insert(f"{end_line}.end", "\n" + result_text)
                result_line = insertion_line

            # One blank separator line plus one new input line.
            calc_text.insert(f"{result_line}.end", "\n\n")
        else:
            return False
    finally:
        end_programmatic_edit()

    last_result = result
    edit_snapshot_text = None
    edit_snapshot_taken = False
    apply_formatting()
    ensure_list_bottom_input_line()
    calc_text.mark_set("insert", "end-1c")
    calc_text.see("insert")
    calc_text.focus_set()
    update_list_status()
    return True


def handle_list_enter(event=None):
    """Finalize a new series or recalculate an edited series with one Enter."""
    global debounce_id

    if debounce_id:
        calc_text.after_cancel(debounce_id)
        debounce_id = None
        if live_formatting_enabled:
            apply_number_format()

    cursor_line = int(calc_text.index("insert").split(".")[0])
    last_line = int(calc_text.index("end-1c").split(".")[0])
    current_text = calc_text.get(
        f"{cursor_line}.0", f"{cursor_line}.end"
    ).strip()

    # Shift+Enter always inserts an ordinary line break. Plain-text note lines
    # also use ordinary Enter because they are not calculation entries.
    if (event and event.state & 0x1) or is_list_annotation_text(current_text):
        insert_list_line_break()
        return "break"

    # Enter on the empty input line has no second/double-Enter meaning.
    if cursor_line == last_line and not current_text:
        update_list_status()
        return "break"

    bounds = find_list_series_bounds(cursor_line)
    if not bounds:
        update_list_status()
        return "break"

    # One Enter both finalizes a new series and updates a historical series.
    recalculate_list_series(bounds, create_result=True)
    return "break"


def insert_list_line_break():
    """Insert a user-requested line break without evaluating the series."""
    take_edit_snapshot_before_change()

    try:
        insertion_index = calc_text.index("sel.first")
        selection_end = calc_text.index("sel.last")
    except tk.TclError:
        insertion_index = calc_text.index("insert")
    else:
        begin_programmatic_edit()
        try:
            calc_text.delete(insertion_index, selection_end)
        finally:
            end_programmatic_edit()

    line_no = int(insertion_index.split(".")[0])
    begin_programmatic_edit()
    try:
        calc_text.insert(insertion_index, "\n")
        calc_text.mark_set("insert", f"{line_no + 1}.0")
    finally:
        end_programmatic_edit()

    calc_text.see("insert")
    calc_text.focus_set()
    apply_formatting()
    update_list_status()


def find_previous_list_result_text(lines, before_line_number):
    """Return the nearest earlier List Mode result without its equals sign."""
    last_index = min(before_line_number - 2, len(lines) - 1)
    for index in range(last_index, -1, -1):
        if is_list_result_text(lines[index]):
            result_text = lines[index].strip()[1:].strip()
            return result_text or None
    return None


def handle_list_operator_key(operator):
    """Insert the next operator line at the current List Mode position."""
    line_no = int(calc_text.index("insert").split(".")[0])
    cursor_col = int(calc_text.index("insert").split(".")[1])
    line_text = calc_text.get(f"{line_no}.0", f"{line_no}.end")
    stripped = canonicalize_operator_symbols(line_text).strip()
    displayed_operator = format_operator_symbols(operator)

    line_tags = set(calc_text.tag_names(f"{line_no}.0"))
    is_list_line = bool(line_tags.intersection({"list_entry", "list_result"}))
    if not is_cursor_on_last_line() and not is_list_line:
        return None

    # Keep signs inside scientific notation on the same line (for example,
    # 1e-3) instead of treating them as the next List Mode operation.
    if (
        operator in ("+", "-")
        and cursor_col > 0
        and line_text[cursor_col - 1:cursor_col] in ("e", "E")
    ):
        return None

    target_line = line_no
    begin_programmatic_edit()
    try:
        if not stripped:
            previous_result = find_previous_list_result_text(
                get_calculator_lines(),
                line_no,
            )
            starts_new_series = find_list_series_bounds(line_no) is None

            if previous_result is not None and starts_new_series:
                # A leading operator continues from the nearest finalized List
                # Mode result, just as a leading operator uses ANS normally.
                calc_text.delete(f"{line_no}.0", f"{line_no}.end")
                calc_text.insert(f"{line_no}.0", previous_result)
                calc_text.insert(f"{line_no}.end", "\n" + displayed_operator)
                target_line = line_no + 1
            else:
                calc_text.insert(f"{line_no}.0", displayed_operator)
        elif stripped in LIST_OPERATORS:
            if stripped == "*" and operator == "*":
                calc_text.delete(f"{line_no}.0", f"{line_no}.end")
                calc_text.insert(
                    f"{line_no}.0",
                    format_operator_symbols("**"),
                )
            elif stripped in ("*", "/", "**") and operator in ("+", "-"):
                calc_text.insert(f"{line_no}.end", displayed_operator)
            else:
                calc_text.delete(f"{line_no}.0", f"{line_no}.end")
                calc_text.insert(f"{line_no}.0", displayed_operator)
        else:
            if (
                not is_list_result_text(line_text)
                and not is_list_annotation_text(line_text)
            ):
                try:
                    parse_list_entry(line_text, last_result)
                except Exception:
                    return "break"
            calc_text.insert(f"{line_no}.end", "\n" + displayed_operator)
            target_line = line_no + 1
    finally:
        end_programmatic_edit()

    calc_text.mark_set("insert", f"{target_line}.end")
    format_current_line_operator_spacing()
    calc_text.see("insert")
    calc_text.focus_set()
    apply_formatting()
    update_list_status()
    return "break"


def update_footer_layout():
    """Keep the optional keypad and List Mode status in a stable order."""
    if "bottom_bar" not in globals():
        return

    keypad_frame.pack_forget()
    status_bar.pack_forget()

    previous_bar = bottom_bar
    if keypad_visible:
        keypad_frame.pack(side="top", fill="x", after=previous_bar)
        previous_bar = keypad_frame

    if list_mode_enabled:
        status_bar.pack(side="top", fill="x", after=previous_bar)


def update_list_mode_ui(prepare_input=False):
    if "status_bar" not in globals():
        return

    update_footer_layout()

    if list_mode_enabled:
        if prepare_input:
            prepare_new_list_series()
        else:
            ensure_list_bottom_input_line()
        update_list_status()

    apply_formatting()


def toggle_list_mode():
    global list_mode_enabled, edit_snapshot_text, edit_snapshot_taken
    list_mode_enabled = bool(list_mode_var.get())
    edit_snapshot_text = None
    edit_snapshot_taken = False
    update_list_mode_ui(prepare_input=list_mode_enabled)
    calc_text.focus_set()


def toggle_keypad():
    global keypad_visible
    keypad_visible = bool(keypad_visible_var.get())
    update_footer_layout()
    calc_text.focus_set()

def evaluate_expression(event=None):
    global last_result
    global edit_snapshot_text, edit_snapshot_taken , debounce_id

    if list_mode_enabled:
        return handle_list_enter(event)
    
    # -----------------------------
    # If a debounce formatting is pending, apply formatting immediately
    # -----------------------------
    if debounce_id:
        calc_text.after_cancel(debounce_id)
        debounce_id = None
        apply_number_format()

    cursor = calc_text.index(tk.INSERT)
    line_no, _ = map(int, cursor.split("."))

    raw_line = calc_text.get(f"{line_no}.0", f"{line_no}.end").strip()
    # -----------------------------
    # FORMAT expression numbers consistently
    # -----------------------------
    #raw_line = format_expression_numbers(raw_line)

    # If we are on the last line (new expression), reset old snapshot
    last_line = int(calc_text.index("end-1c").split(".")[0])
    if line_no == last_line:
        edit_snapshot_text = None
        edit_snapshot_taken = False

    # -----------------------------
    # If user is editing previous line
    # -----------------------------
    if edit_snapshot_taken and not is_cursor_on_last_line():
        
        edited_expr = raw_line.rstrip("=").strip()

        calc_text.edit_modified(False)

        begin_programmatic_edit()
        try:
            calc_text.delete("1.0", tk.END)
            calc_text.insert("1.0", edit_snapshot_text)
            
            calc_text.mark_set("insert", "end-1c")

            if calc_text.index("end-1c") != "1.0" and calc_text.get("end-2c", "end-1c") != "\n":
                calc_text.insert("end", "\n")

            calc_text.insert("end", edited_expr)

            # The edited history line has now become the new bottom input
            # line. Refresh the saved cursor position so automatic additions
            # such as balancing parentheses are written to this new line,
            # not to the historical line that was originally edited.
            cursor = calc_text.index("end-1c")
            calc_text.mark_set("insert", cursor)
        finally:
            end_programmatic_edit()

        edit_snapshot_text = None
        edit_snapshot_taken = False
        
        calc_text.edit_modified(False)
        raw_line = edited_expr

        # return evaluate_expression()
	

    # -----------------------------
    # Ignore empty line 
    # -----------------------------
    if not raw_line:
        ensure_bottom_empty_line()
        apply_formatting()
        return "break"

    cmd = raw_line.lower()
    if cmd in ("c", "clr", "ز"):
        clear_screen()
        return "break"

    # -----------------------------
    # Ignore non expression lines
    # -----------------------------
    #if re.search(r"[A-Za-z]", raw_line) and "ANS" not in raw_line.upper():
    #    apply_formatting()
    #    ensure_bottom_empty_line()
    #    return "break"


    if raw_line.endswith("="):
        raw_line = raw_line[:-1].strip()

    expr = canonicalize_operator_symbols(
        strip_digit_separators(raw_line)
    ).strip()

    # Remove leading zeros only from the expression used for calculation
    expr = re.sub(
        r'(?<![\d.])0+(\d+)(?![\d.])',
        lambda m: str(int(m.group(0))),
        expr
    )
    
    expr = expr.replace("[", "(").replace("]", ")")

    #expr = get_valid_expression(expr)


    # Prepend last_result if expression starts with operator
    add_result_to_BOL=False
    if expr and expr[0] in "+-*/^²" and last_result is not None:
        expr = f"{last_result}{expr}"
        raw_line = f"{display_number_str(str(last_result))} {raw_line}"
        add_result_to_BOL=True

    # Auto-balance parentheses. A left-to-right scan is necessary because an
    # expression may have equal counts but still be out of order, for example
    # "2+3)/(4+5".
    paren_prefix, paren_suffix = get_parenthesis_padding(expr)
    expr = paren_prefix + expr + paren_suffix

    add_result_to_EOL=False
    # If it only contains empty sqrt, insert ANS
    if expr==("√()") and last_result is not None:
        expr = expr.replace("√(", f"√(ANS", 1)
        add_result_to_EOL=True

    #print(expr)

    # Implicit multiplication
    expr = re.sub(r'pi', 'π', expr, flags=re.IGNORECASE)

    # Keep the square exponent separate from any following factor. For
    # example, 5²5 must become 5^(2)*5, not 5^25.
    expr = expr.replace("²", "^(2)")

    # A trailing decimal point is still part of the number. Interpret
    # 2.(...) as 2.*(...) rather than leaving invalid Python syntax.
    expr = re.sub(r"(?<=\d)\.(?=\()", ".*", expr)
    
    expr = re.sub(r"(\d|\)|π|\bANS)\(", r"\1*(", expr, flags=re.IGNORECASE)
    expr = re.sub(r"\)(?=(?:\d|\.\d))", r")*", expr)
    expr = re.sub(r"(\d|\)|π|\bANS)√", r"\1*√", expr, flags=re.IGNORECASE)   # before sqrt
    expr = re.sub(r"(\d|\)|π|\bANS)π", r"\1*π", expr, flags=re.IGNORECASE)   # before pi
    expr = re.sub(r"(\d|\)|π|\bANS)(ANS)\b", r"\1*\2", expr, flags=re.IGNORECASE)

    expr = expr.replace("^", "**")
    expr = expr.replace("√(", "math.sqrt(")
    # --- PI support ---
    expr = expr.replace("π", "math.pi")



    #print( expr)

    expr = get_valid_expression(expr)
    
    # ANS support
    expr = re.sub(r"\bANS\b", str(last_result), expr, flags=re.IGNORECASE)

    try:
        result = safe_evaluate_expression(expr)

    except Exception:
        edit_snapshot_text = None
        edit_snapshot_taken = False
        apply_formatting()
        ensure_bottom_empty_line()
        return "break"

    result = normalize_result(result,MAX_DIGITS)
    
    # -----------------------------
    # Display result (NEW LINE ONLY)
    # -----------------------------
    total_lines = int(calc_text.index("end-1c").split(".")[0])

    line_no, _ = map(int, cursor.split("."))


    # Insert last_result at the beginning of the current line
    if add_result_to_BOL :
        calc_text.insert(
            f"{line_no}.0",
            display_number_str(str(last_result)) + THIN_SPACE,
        )
        add_result_to_BOL=False
    if add_result_to_EOL :
        calc_text.insert("end-1c","" + display_number_str(str(last_result)))
        add_result_to_EOL=False

    begin_programmatic_edit()
    try:
        # Show automatically inserted parentheses in the calculation history.
        # Prefix parentheses are inserted after a possible implicit ANS value,
        # so an input such as "+2)" becomes "(ANS+2)" rather than "ANS(+2)".
        if paren_prefix:
            calc_text.insert(f"{line_no}.0", paren_prefix)
        if paren_suffix:
            calc_text.insert(f"{line_no}.end", paren_suffix)

        calc_text.insert("end-1c", " =")
        calc_text.insert("end-1c", "\n" + display_number_str(str(result)))
    finally:
        end_programmatic_edit()

    last_result = result

    # Ensure exactly ONE empty line after result
    # Remove any blank line after result
    #calc_text.delete(f"{line_no+2}.0", f"{line_no+2}.end")

    apply_formatting()

    # Move cursor after result
    calc_text.mark_set("insert", f"{line_no+2}.0")
    calc_text.see("insert")

    ensure_bottom_empty_line()

    return "break"

def get_list_formatting_lines(lines):
    """Return one-based entry/result line sets for List Mode styling/navigation."""
    entry_lines = set()
    result_lines = set()

    for index, line in enumerate(lines):
        if not is_list_result_text(line):
            continue

        result_lines.add(index + 1)
        entry_index = index - 1
        while entry_index >= 0 and lines[entry_index].strip():
            if is_list_result_text(lines[entry_index]):
                break
            entry_lines.add(entry_index + 1)
            entry_index -= 1

    # Also mark the unfinished block currently being entered. Two trailing
    # empty lines mean there is no active block—only a series separator.
    if list_mode_enabled:
        trailing_empty_lines = 0
        for line in reversed(lines):
            if line.strip():
                break
            trailing_empty_lines += 1

        last_nonempty = len(lines) - trailing_empty_lines - 1
        if (
            last_nonempty >= 0
            and trailing_empty_lines <= 1
            and not is_list_result_text(lines[last_nonempty])
        ):
            start = last_nonempty
            while start > 0:
                previous = lines[start - 1]
                if not previous.strip() or is_list_result_text(previous):
                    break
                start -= 1
            entry_lines.update(range(start + 1, last_nonempty + 2))

    return entry_lines, result_lines


FRACTION_PATTERN = re.compile(r"(?<![\w.])(?:\d[\d,']*)?\.(\d+)")
OPERATOR_FORMAT_PATTERN = re.compile(r"[+\-*/×÷=^√²]")


def apply_fraction_formatting(line_number, line, is_result_line=False):
    """Display digits after a decimal point in a slightly smaller font."""
    if not live_formatting_enabled:
        return

    tag_name = "result_fraction" if is_result_line else "fraction"
    for match in FRACTION_PATTERN.finditer(line):
        fraction_start, fraction_end = match.span(1)
        calc_text.tag_add(
            tag_name,
            f"{line_number}.{fraction_start}",
            f"{line_number}.{fraction_end}",
        )


def apply_operator_formatting(line_number, line):
    """Bold operators in calculation tokens without styling description text."""
    for token_match in re.finditer(r"\S+", line):
        token = token_match.group(0)
        if not is_displayed_calculation_part(token):
            continue

        for operator_match in OPERATOR_FORMAT_PATTERN.finditer(token):
            start = token_match.start() + operator_match.start()
            end = token_match.start() + operator_match.end()
            calc_text.tag_add(
                "operator",
                f"{line_number}.{start}",
                f"{line_number}.{end}",
            )


def apply_formatting():
    lines = calc_text.get("1.0", "end-1c").split("\n")
    list_entry_lines, list_result_lines = get_list_formatting_lines(lines)

    for i, line in enumerate(lines):
        start = f"{i+1}.0"
        end = f"{i+1}.end"
        calc_text.tag_remove("expr", start, end)
        calc_text.tag_remove("result", start, end)
        calc_text.tag_remove("invalid", start, end)
        calc_text.tag_remove("list_entry", start, end)
        calc_text.tag_remove("list_result", start, end)
        calc_text.tag_remove("fraction", start, end)
        calc_text.tag_remove("result_fraction", start, end)
        calc_text.tag_remove("operator", start, end)

        stripped = strip_digit_separators(line.strip())

        if not stripped:
            continue

        apply_operator_formatting(i + 1, line)

        if i + 1 in list_result_lines:
            calc_text.tag_add("result", start, end)
            calc_text.tag_add("list_result", start, end)
            apply_fraction_formatting(i + 1, line, is_result_line=True)
            continue

        if i + 1 in list_entry_lines:
            calc_text.tag_add("list_entry", start, end)

        is_normal_result_line = (
            i > 0
            and lines[i - 1].rstrip().endswith("=")
            and re.fullmatch(r"-?\d+(\.\d+)?", stripped) is not None
        )

        if i + 1 not in list_entry_lines and is_normal_result_line:
            calc_text.tag_add("result", start, end)
            apply_fraction_formatting(i + 1, line, is_result_line=True)
        else:
            # Preserve every word, unit and description, but show which tokens
            # participate in the calculation and which ones are ignored.
            for match in re.finditer(r"\S+", line):
                token_start, token_end = match.span()
                token_tag = (
                    "expr"
                    if is_displayed_calculation_part(match.group(0))
                    else "invalid"
                )
                calc_text.tag_add(
                    token_tag,
                    f"{i+1}.{token_start}",
                    f"{i+1}.{token_end}"
                )
            apply_fraction_formatting(i + 1, line)

def reformat_last_result():
    global last_result
    last_line = int(calc_text.index("end-2c").split(".")[0])  # last non-empty line
    last_text = calc_text.get(f"{last_line}.0", f"{last_line}.end").strip()

    # Only reformat if it looks like a number
    try:
        val = float(strip_digit_separators(last_text))
    except ValueError:
        return  # last line not a number, do nothing

    # Normalize with new MAX_DIGITS
    formatted = display_number_str(str(normalize_result(val, decimals=MAX_DIGITS)))

    # Replace last line safely
    calc_text.delete(f"{last_line}.0", f"{last_line}.end")
    calc_text.insert(f"{last_line}.0", formatted)

    apply_formatting()


# ---------- UI actions ----------
def increase_font():
    global current_font_size
    current_font_size += 1
    update_font()

def decrease_font():
    global current_font_size
    if current_font_size > 8:
        current_font_size -= 1
        update_font()


def handle_ctrl_mousewheel(event):
    """Change display size while Ctrl is held, without scrolling the text."""
    if event.delta > 0:
        increase_font()
    elif event.delta < 0:
        decrease_font()
    return "break"

def update_font():
    calc_text.config(font=("Calibri", current_font_size))
    #calc_text.config(font=("Lucida Console", current_font_size))

    calc_text.tag_configure("invalid", font=("Calibri", current_font_size))
    calc_text.tag_configure(
        "operator",
        font=("Calibri", current_font_size, "bold"),
    )
    calc_text.tag_configure(
        "result",
        font=("Calibri", current_font_size, "bold"),
        spacing3=RESULT_BOTTOM_SPACING,
    )
    calc_text.tag_configure(
        "list_result",
        font=("Calibri", current_font_size, "bold"),
        spacing3=RESULT_BOTTOM_SPACING,
    )
    fraction_size = max(8, current_font_size - 3)
    calc_text.tag_configure("fraction", font=("Calibri", fraction_size))
    calc_text.tag_configure(
        "result_fraction",
        font=("Calibri", fraction_size, "bold"),
    )


def update_digit_status():
    if "digit_status_var" in globals():
        digit_status_var.set(f"Digits: {MAX_DIGITS}")

def clear_screen():
    global last_result,edit_snapshot_text,edit_snapshot_taken
    begin_programmatic_edit()
    try:
        calc_text.delete("1.0", tk.END)
    finally:
        end_programmatic_edit()
    last_result = 0
    edit_snapshot_text = None
    edit_snapshot_taken = False
    if list_mode_enabled:
        set_list_status("Result: 0")
# ---------- Save / Load state ----------
def save_state():
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(root.geometry() + "\n")
        f.write(str(current_font_size) + "\n")
        f.write(str(MAX_DIGITS) + "\n")
        f.write(str(last_result) + "\n")
        f.write(f"LIVE_FORMATTING={int(live_formatting_enabled)}\n")
        separator_code = {
            ",": "comma",
            "'": "apostrophe",
        }.get(digit_separator, "comma")
        f.write(f"DIGIT_SEPARATOR={separator_code}\n")
        f.write(f"PRETTY_OPERATORS={int(pretty_operators_enabled)}\n")
        f.write(f"KEYPAD_VISIBLE={int(keypad_visible)}\n")
        f.write(f"LIST_MODE={int(list_mode_enabled)}\n")
        f.write(calc_text.get("1.0", tk.END))

def load_state():
    global current_font_size, last_result, MAX_DIGITS
    global live_formatting_enabled, digit_separator, list_mode_enabled
    global keypad_visible, pretty_operators_enabled
    state_path = STATE_FILE
    if not os.path.exists(state_path):
        state_path = resource_path(DEFAULT_STATE_FILE)
    if not os.path.exists(state_path):
        return
    with open(state_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    root.geometry(lines[0].strip())
    current_font_size = int(lines[1].strip())
    MAX_DIGITS=int(lines[2].strip())
    update_digit_status()
    last_result=float(lines[3].strip())

    # Older state files have calculation history immediately after line 4.
    # The marker keeps those files compatible with this newer version.
    history_start = 4
    while history_start < len(lines):
        setting_line = lines[history_start]
        if setting_line.startswith("LIVE_FORMATTING="):
            saved_value = setting_line.partition("=")[2].strip()
            live_formatting_enabled = saved_value != "0"
        elif setting_line.startswith("DIGIT_SEPARATOR="):
            saved_value = setting_line.partition("=")[2].strip().lower()
            digit_separator = {
                "comma": ",",
                "apostrophe": "'",
            }.get(saved_value, ",")
        elif setting_line.startswith("DISPLAY_FONT="):
            # Compatibility with the temporary font-preview versions.
            # Calibri is fixed again, so the saved family is simply discarded.
            pass
        elif setting_line.startswith("PRETTY_OPERATORS="):
            saved_value = setting_line.partition("=")[2].strip()
            pretty_operators_enabled = saved_value != "0"
        elif setting_line.startswith("KEYPAD_VISIBLE="):
            saved_value = setting_line.partition("=")[2].strip()
            keypad_visible = saved_value != "0"
        elif setting_line.startswith("LIST_MODE="):
            saved_value = setting_line.partition("=")[2].strip()
            list_mode_enabled = saved_value != "0"
        else:
            break
        history_start += 1

    begin_programmatic_edit()
    try:
        calc_text.insert("1.0", "".join(lines[history_start:]).rstrip("\n"))
    finally:
        end_programmatic_edit()    
    if list_mode_enabled:
        ensure_list_bottom_input_line()
    else:
        ensure_bottom_empty_line()
    update_font()
    reformat_operator_symbols(pretty_operators_enabled)
    # Enforce the saved preference immediately, including histories created by
    # older versions that could retain separators while formatting was disabled.
    reformat_entire_history(live_formatting_enabled)
    reformat_operator_spacing()

def on_close():
    tray_shutdown_event.set()
    save_state()

    try:
        if tray_icon is not None:
            tray_icon.stop()
    except Exception:
        pass

    root.destroy()

def handle_keypress(event):
    global is_formatting, is_pasting, last_key_pressed, last_key_action

    last_key_pressed = event.char
    last_key_action = event.keysym

    if event.state & 0x4 and event.keysym.lower() == "v":
        take_edit_snapshot_before_change()
        is_pasting = True
        return

    # Do not intercept Delete/Backspace
    if event.keysym in ("BackSpace", "Delete"):
        take_edit_snapshot_before_change()
        return

    if is_formatting:
        return "break"

    # KeyPress occurs before Tk inserts the character. Capture the unedited
    # history here so Esc never keeps the first typed digit.
    if (
        not (event.state & 0x4)
        and event.char
        and event.keysym not in ("Return", "Escape")
    ):
        take_edit_snapshot_before_change()

    operator_by_keysym = {
        "plus": "+",
        "KP_Add": "+",
        "minus": "-",
        "KP_Subtract": "-",
        "asterisk": "*",
        "multiply": "*",
        "KP_Multiply": "*",
        "slash": "/",
        "KP_Divide": "/",
    }
    list_operator = (
        canonicalize_operator_symbols(event.char)
        if event.char and event.char in "+-*/×÷"
        else operator_by_keysym.get(event.keysym)
    )
    if list_mode_enabled and not (event.state & 0x4) and list_operator:
        last_key_pressed = list_operator
        take_edit_snapshot_before_change()
        handled = handle_list_operator_key(list_operator)
        if handled:
            return handled

    # Insert arithmetic operators ourselves so their symbol choice and compact
    # spacing are identical for the keyboard and the on-screen keypad.
    if not (event.state & 0x4) and list_operator:
        last_key_pressed = list_operator
        insert_spaced_operator(list_operator)
        return "break"




    # Context-aware Persian key replacement (only check left character)
    if is_persian_layout() and event.char == "ث":
        cursor_index = calc_text.index("insert")
        line_no, col = map(int, cursor_index.split("."))
        line_text = calc_text.get(f"{line_no}.0", f"{line_no}.end")

        # Check left character
        if col > 0 and line_text[col - 1].isdigit():
            char_to_insert = "e"
        else:
            char_to_insert = "ث"

        try:
            calc_text.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        calc_text.insert("insert", char_to_insert)
        last_key_pressed = char_to_insert
        return "break"  # prevent default insertion








    # Persian/English swap
    swap_map_persian = {"(": ")", ")": "(", "ج": "(", "چ": ")"}
    swap_map_english = {"[": "(", "]": ")"}

    try:
        swap_map = swap_map_persian if is_persian_layout() else swap_map_english
    except Exception:
        swap_map = swap_map_english

    if event.char in swap_map:
        try:
            calc_text.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        inserted = swap_map[event.char]
        calc_text.insert("insert", inserted)
        last_key_pressed = inserted
        return "break"

    
    # Allow only digits/dot/minus to be formatted
    # Allow Ctrl shortcuts (Ctrl+C, Ctrl+V, Ctrl+A, Ctrl+X)
    if event.state & 0x4:  # Ctrl key is pressed
        return

    # Allow only digits/dot/minus to be formatted
    if not (event.char.isdigit() or event.char == '.' or event.char == '-'):
        return

def handle_control_shortcut(event):
    """Handle common shortcuts by physical Windows key, independent of layout."""
    if not (event.state & 0x4):
        return

    # On Windows, event.keycode is the layout-independent virtual-key code.
    # This keeps the shortcuts working when Persian is the active keyboard.
    if event.keycode == ord("C"):
        calc_text.event_generate("<<Copy>>")
        return "break"
    if event.keycode == ord("V"):
        paste_text()
        return "break"
    if event.keycode == ord("X"):
        take_edit_snapshot_before_change()
        calc_text.event_generate("<<Cut>>")
        return "break"
    if event.keycode == ord("A"):
        calc_text.tag_add(tk.SEL, "1.0", "end-1c")
        calc_text.mark_set("insert", "end-1c")
        calc_text.see("insert")
        return "break"

def format_after_edit(event=None):
    global debounce_id, is_pasting, last_key_pressed

    # Ignore navigation keys so cursor can move normally
    if event and event.keysym in (
        "Left", "Right", "Up", "Down",
        "Home", "End", "Prior", "Next"
    ):
        return
    # Skip formatting if operator is pressed
    #if last_key_pressed in "+-*/^()√²=π":
    #    return
        
   
    if event and event.char and event.char in "+-*/×÷^()√²=π":
        return
    
    # If we are pasting, skip formatting once
    if is_pasting:
        is_pasting = False

        # cancel any pending formatting
        if debounce_id:
            calc_text.after_cancel(debounce_id)
            debounce_id = None
        return
    #messagebox.showinfo("Title", "This is an info message")
    # Cancel previous scheduled formatting
    if debounce_id:
        calc_text.after_cancel(debounce_id)
        debounce_id = None


def is_unary_minus(line, index):
    """Returns True if '-' is a unary minus (negative sign)"""
    if index == 0:
        return True
    prev = line[index - 1]
    return prev in "+-*/×÷^("

def find_number_boundaries(line, cursor_col):
    """
    Finds the start and end of a number around the cursor.
    Handles supported separators, decimal points, and unary minus.
    """
    if not line:
        return cursor_col, cursor_col

    # Expand left
    left = cursor_col - 1
    while left >= 0:
        ch = line[left]
        if ch.isdigit() or ch in ",.'":
            left -= 1
        ###elif ch == "-" and (left == 0 or line[left - 1] in "+-*/^("):
        ###    left -= 1
        else:
            break
    start = left + 1

    # Expand right
    right = cursor_col
    while right < len(line):
        ch = line[right]
        if ch.isdigit() or ch in ",.'":
            right += 1
        ###elif ch == "-" and (right == 0 or line[right - 1] in "+-*/^("):
        ###    right += 1
        else:
            break
    return start, right

OP_CHARS = set("+-*/×÷^()=√²πeEث")  # add more if you want

def _scan_number_left(line: str, end_pos: int):
    """
    Returns (start, end) of a number that ends at end_pos (inclusive).
    Supports digits, grouping separators, decimal point, and unary minus.
    """
    if end_pos < 0 or end_pos >= len(line):
        return None

    i = end_pos
    # must end with digit or '.' (like "12."), allow grouping separators
    if not (line[i].isdigit() or line[i] in ".,'"):
        return None

    while i >= 0 and (line[i].isdigit() or line[i] in ",.'"):
        i -= 1

    start = i + 1

    # include unary minus if directly before and valid unary position
    if start - 1 >= 0 and line[start - 1] == "-":
        if start - 1 == 0 or line[start - 2] in "+-*/×÷^(":
            start -= 1

    return (start, end_pos + 1)  # end is exclusive


def _scan_number_right(line: str, start_pos: int):
    """
    Returns (start, end) of a number that starts at start_pos.
    Supports digits, grouping separators and decimal point.
    (Does not treat '-' as part of number here because '-' is an operator you just inserted.)
    """
    if start_pos < 0 or start_pos >= len(line):
        return None

    if not (line[start_pos].isdigit() or line[start_pos] in "."):
        return None

    j = start_pos
    while j < len(line) and (line[j].isdigit() or line[j] in ",.'"):
        j += 1

    return (start_pos, j)


def _format_span_in_line(line_no: int, start: int, end: int, keep_cursor_col: int):
    """
    Replace the substring [start:end] on line_no with formatted number.
    Returns updated (new_cursor_col, delta_len) where delta_len is change in text length.
    """
    number_str = calc_text.get(f"{line_no}.{start}", f"{line_no}.{end}")
    #print(number_str)
    raw_number = strip_digit_separators(number_str)

    # Only format real numbers
    if not re.fullmatch(r"-?\d+(\.\d*)?|\.\d+", raw_number):
        return keep_cursor_col, 0

    formatted = format_number_str(raw_number)

    #zeroz
    if raw_number.startswith(("0", "-0")):
        return keep_cursor_col, 0

    if formatted == number_str:
        return keep_cursor_col, 0

    # Do the replacement
    before_len = end - start
    after_len = len(formatted)
    delta = after_len - before_len

    calc_text.delete(f"{line_no}.{start}", f"{line_no}.{end}")
    calc_text.insert(f"{line_no}.{start}", formatted)

    # If cursor is after this span, shift it by delta
    if keep_cursor_col > end:
        keep_cursor_col += delta
    elif keep_cursor_col >= start and keep_cursor_col <= end:
        # cursor was inside replaced number: keep it at end of formatted span
        keep_cursor_col = start + after_len

    return keep_cursor_col, delta



def apply_number_format():
    global is_formatting

    if not live_formatting_enabled:
        return

    if is_formatting:
        return  # prevent re-entry

    cursor_index = calc_text.index("insert")
    line_no, col = map(int, cursor_index.split("."))
    line_text = calc_text.get(f"{line_no}.0", f"{line_no}.end")


    # --- NEW: operator-aware formatting ---
    # If last key was an operator, format around it based on position
    if last_key_pressed in OP_CHARS:
        # The cursor is after the operator's optional trailing thin space.
        op_index = col - 1
        while op_index >= 0 and line_text[op_index].isspace():
            op_index -= 1
        if op_index < 0 or op_index >= len(line_text):
            return

        # Determine if operator is at end of line (ignoring trailing spaces)
        stripped_right = line_text.rstrip()
        op_at_end = (op_index == len(stripped_right) - 1)

        # We'll keep cursor where it currently is (after operator)
        new_cursor_col = col

        # Format left number (ends just before operator)
        left_end = op_index - 1
        while left_end >= 0 and line_text[left_end].isspace():
            left_end -= 1
        left_span = _scan_number_left(line_text, left_end)
        if left_span:
            begin_programmatic_edit()
            try:
                new_cursor_col, _ = _format_span_in_line(line_no, left_span[0], left_span[1], new_cursor_col)
            finally:
                end_programmatic_edit()

            # Update line_text since we changed it
            line_text = calc_text.get(f"{line_no}.0", f"{line_no}.end")

            # If we formatted left side, operator position may have shifted.
            # Recompute the operator position because number separators may
            # have shifted both the operator and its thin spaces.
            op_index = new_cursor_col - 1
            while op_index >= 0 and line_text[op_index].isspace():
                op_index -= 1

        if not op_at_end:
            # Only format right side if the operator was inserted inside a number:
            # meaning there are number chars on BOTH sides of operator.
            left_index = op_index - 1
            while left_index >= 0 and line_text[left_index].isspace():
                left_index -= 1
            right_index = op_index + 1
            while right_index < len(line_text) and line_text[right_index].isspace():
                right_index += 1

            left_char_ok = (
                left_index >= 0
                and (
                    line_text[left_index].isdigit()
                    or line_text[left_index] in ".,'"
                )
            )
            right_char_ok = (
                right_index < len(line_text)
                and (
                    line_text[right_index].isdigit()
                    or line_text[right_index] in ".,'"
                )
            )

            if left_char_ok and right_char_ok:
                right_span = _scan_number_right(line_text, right_index)
                if right_span:
                    begin_programmatic_edit()
                    try:
                        new_cursor_col, _ = _format_span_in_line(line_no, right_span[0], right_span[1], new_cursor_col)
                    finally:
                        end_programmatic_edit()

        # Restore cursor (after operator)
        calc_text.mark_set("insert", f"{line_no}.{new_cursor_col}")
        return


    

    # Skip if line empty
    if not line_text.strip():
        return

    # Find number under cursor
    number_start, number_end = find_number_boundaries(line_text, col)
    number_str = line_text[number_start:number_end]
    #print(number_str)
    
    # Skip if number contains ANS or other keywords
    if any(kw in number_str.upper() for kw in ALLOWED_KEYWORDS):
        return

    ## Strip grouping separators for formatting
    raw_number = strip_digit_separators(number_str)
    if not re.fullmatch(r"-?\d+(\.\d*)?|\.\d+", raw_number):
        return  # not a number, skip

    # Skip formatting if the number is all zeros (like 000 or 00)
    #if raw_number.lstrip("-").replace(".", "") == "0" * len(raw_number.lstrip("-").replace(".", "")):
    #    return

    # Skip formatting if the number starts with zeroz
    #if raw_number.startswith(("0", "-0")):
    #    return 



    # Determine cursor position relative to start of number
    cursor_in_number = col - number_start  # a
    separators_before_cursor = sum(
        character in GROUPING_SEPARATORS
        for character in number_str[:cursor_in_number]
    )
    cursor_in_raw = cursor_in_number - separators_before_cursor

    #print(cursor_in_raw)




    formatted_number = format_number_str(raw_number)
    
    # Skip if nothing changed
    if formatted_number == number_str:
        return

    ## Calculate cursor position relative to number start
    #cursor_in_number = col - number_start
    #digits_before_cursor = len([c for c in raw_number[:cursor_in_number] if c.isdigit() or c == "."])
    ##print (cursor_in_number , col , number_start)
    
    # Calculate new cursor position in formatted number
    digits_seen = 0
    new_cursor_pos = 0
    if cursor_in_raw==0:
        new_cursor_pos = 0
    else:
        for i, ch in enumerate(formatted_number):
            if ch.isdigit() or ch == ".":
                digits_seen += 1
            if digits_seen >= cursor_in_raw:
                new_cursor_pos = i +1
                break
        else:
            new_cursor_pos = len(formatted_number)

    # Deleting a separator with Delete should leave the cursor after the
    # restored separator. Backspace is the mirror action and should leave it
    # before the separator instead.
    if last_key_action != "BackSpace":
        while (
            new_cursor_pos < len(formatted_number)
            and formatted_number[new_cursor_pos] in GROUPING_SEPARATORS
        ):
            new_cursor_pos += 1

    #print (cursor_in_number,new_cursor_pos)

    # Replace text safely
    begin_programmatic_edit()
    try:
        is_formatting = True
        calc_text.delete(f"{line_no}.{number_start}", f"{line_no}.{number_end}")
        calc_text.insert(f"{line_no}.{number_start}", formatted_number)
        calc_text.mark_set("insert", f"{line_no}.{number_start + new_cursor_pos}")
    finally:
        is_formatting = False
        end_programmatic_edit()

    # Replacing the number also removes any character-level tags inside it.
    # Restore fraction sizing (and the other display tags) after the rewrite.
    apply_formatting()

 
def on_text_modified(event=None):
    global edit_snapshot_text, edit_snapshot_taken, debounce_id, is_programmatic_edit

    if is_programmatic_edit:
        calc_text.edit_modified(False)
        return

    if not calc_text.edit_modified():
        return

    # Take snapshot once (only for real user edits)
    if not edit_snapshot_taken:
        edit_snapshot_text = calc_text.get("1.0", "end-1c")
        edit_snapshot_taken = True

    # Debounce formatting when live formatting is enabled.
    if debounce_id:
        calc_text.after_cancel(debounce_id)
        debounce_id = None

    if live_formatting_enabled:
        debounce_id = calc_text.after(150, apply_number_format)

    calc_text.after_idle(apply_formatting)

    if list_mode_enabled:
        calc_text.after_idle(update_list_result_live)
    calc_text.edit_modified(False)


    
def is_cursor_on_last_line():
    cursor_line = int(calc_text.index("insert").split(".")[0])
    last_line = int(calc_text.index("end-1c").split(".")[0])
    return cursor_line == last_line

def is_last_line_empty():
    last_line = int(calc_text.index("end-1c").split(".")[0])
    return calc_text.get(f"{last_line}.0", f"{last_line}.end").strip() == ""

def restore_snapshot_and_jump_to_end():
    global edit_snapshot_text, edit_snapshot_taken

    if not edit_snapshot_taken or not edit_snapshot_text:
        return
    begin_programmatic_edit()
    try:
        calc_text.delete("1.0", tk.END)
        calc_text.insert("1.0", edit_snapshot_text)
    finally:
        end_programmatic_edit()
    
        
    edit_snapshot_text = None
    edit_snapshot_taken = False

    apply_formatting()
    if list_mode_enabled:
        ensure_list_bottom_input_line()
    else:
        ensure_bottom_empty_line()

    calc_text.mark_set("insert", "end-1c")
    calc_text.see("insert")

def handle_escape(event=None):
    # Restore an edited history line first, if necessary.
    if edit_snapshot_taken:
        restore_snapshot_and_jump_to_end()

    # Esc always returns focus to the bottom empty input line, even when there
    # was no edit to restore.
    if list_mode_enabled:
        ensure_list_bottom_input_line()
        update_list_status()
    else:
        ensure_bottom_empty_line()
    calc_text.mark_set("insert", "end-1c")
    calc_text.see("insert")
    calc_text.focus_set()
    return "break"


def copy_text():
    # Copy current selection or entire last line if nothing selected
    try:
        selected = calc_text.get("sel.first", "sel.last")
    except tk.TclError:
        # no selection → copy last line
        last_line = int(calc_text.index("end-2c").split(".")[0])
        selected = calc_text.get(f"{last_line}.0", f"{last_line}.end")
    root.clipboard_clear()
    root.clipboard_append(selected)
    root.update()  # keep clipboard active

def paste_text():
    try:
        # Get text from clipboard
        text = format_operator_spacing_text(
            format_operator_symbols(root.clipboard_get())
        )
        # Insert at current cursor position
        take_edit_snapshot_before_change()
        try:
            selection_start = calc_text.index("sel.first")
            selection_end = calc_text.index("sel.last")
            calc_text.delete(selection_start, selection_end)
            calc_text.mark_set("insert", selection_start)
        except tk.TclError:
            pass
        calc_text.insert(tk.INSERT, text)
        calc_text.focus_set()
    except tk.TclError:
        # Clipboard empty or unavailable
        pass

def format_number_at_cursor(text_widget):
    cursor_index = text_widget.index("insert")
    line_no, col = map(int, cursor_index.split('.'))
    line_start = f"{line_no}.0"
    line_end = f"{line_no}.end"

    line_text = text_widget.get(line_start, line_end)

    # Find all numbers with their spans
    numbers = list(re.finditer(r'\d+(\.\d+)?', line_text))

    target_number = None
    for match in numbers:
        start, end = match.span()
        # Check if cursor is at or next to this number
        if start <= col <= end or col == start:
            target_number = (start, end, match.group())
            break

    if target_number:
        start, end, num_str = target_number
        # Replace with formatted version
        formatted = format_number_str(num_str)
        text_widget.delete(f"{line_start}+{start}c", f"{line_start}+{end}c")
        text_widget.insert(f"{line_start}+{start}c", formatted)

def toggle_live_formatting():
    global live_formatting_enabled, debounce_id

    live_formatting_enabled = bool(live_formatting_var.get())

    if debounce_id:
        calc_text.after_cancel(debounce_id)
        debounce_id = None

    # Apply the new choice immediately to formulas, answers and older lines.
    reformat_entire_history(live_formatting_enabled)

    if list_mode_enabled:
        update_list_status()

    calc_text.focus_set()


def set_digit_separator(separator):
    """Change thousands separator and immediately refresh existing history."""
    global digit_separator, debounce_id

    if separator not in (",", "'"):
        separator = ","
    digit_separator = separator

    if debounce_id:
        calc_text.after_cancel(debounce_id)
        debounce_id = None

    reformat_entire_history(live_formatting_enabled)

    if list_mode_enabled:
        update_list_status()

    calc_text.focus_set()


def toggle_pretty_operators():
    global pretty_operators_enabled

    pretty_operators_enabled = bool(pretty_operators_var.get())
    reformat_operator_symbols(pretty_operators_enabled)
    reformat_operator_spacing()

    if list_mode_enabled:
        update_list_status()

    calc_text.focus_set()

def set_digits(n):
    global MAX_DIGITS
    MAX_DIGITS = n
    update_digit_status()
    #messagebox.showinfo("Precision", f"Result digits set to {MAX_DIGITS}")
    # Update menu check marks
    for d, var in digit_vars.items():
        var.set(1 if d == n else 0)
    redo_last_result()
        
def show_precision_menu(event):
    precision_menu.tk_popup(event.x_root, event.y_root)

def show_right_click_menu(event):
    right_click_menu.tk_popup(event.x_root, event.y_root)

def redo_last_result():
    global last_result

    total_lines = int(calc_text.index("end-1c").split(".")[0])
    if total_lines < 2:
        return  # nothing to redo

    # The last expression is the line before the last result
    last_expr_line_no = total_lines - 2
    last_expr = calc_text.get(f"{last_expr_line_no}.0", f"{last_expr_line_no}.end").strip()

    if not last_expr:
        return

    # --- Delete last result lines ---
    # Remove last line (the result)
    calc_text.delete(f"{last_expr_line_no+1}.0", f"{total_lines}.0")
    # Remove '=' at end of expression line if present
    #if line_text.endswith("="):
    #    calc_text.delete(f"{last_expr_line_no}.end-1c", f"{last_expr_line_no}.end")

    # --- Set cursor at expression line ---
    cursor_index = f"{last_expr_line_no}.0"
    calc_text.mark_set("insert", cursor_index)

    # --- Evaluate expression and display result ---
    evaluate_expression()

def toggle_topmost():
    current = root.attributes('-topmost')
    root.attributes('-topmost', not current)
    
    # Optional: change button appearance
    if root.attributes('-topmost'):
        btn_top.config(relief="sunken", text="📌")
    else:
        btn_top.config(relief="raised", text="📍")




# ---------- GUI ----------

root = tk.Tk()
root.withdraw()

root.title("Mini Calculator")
try:
    root.iconbitmap(resource_path("mini_calc.ico"))
except (OSError, tk.TclError):
    # Keep the source version usable even when the optional icon is absent.
    pass
root.protocol("WM_DELETE_WINDOW", on_close)


footer = tk.Frame(root)
footer.pack(side="bottom", fill="x")

bottom_bar = tk.Frame(footer)
bottom_bar.pack(side="top", fill="x")

# The optional numeric keypad is packed below bottom_bar after state is loaded.
keypad_frame = tk.Frame(footer, padx=3, pady=2)

# This bar is packed only while List Mode is active.
status_bar = tk.Frame(footer, borderwidth=1, relief="sunken")
tk.Label(status_bar, text="List Mode", foreground="#505050").pack(
    side="left", padx=5, pady=1
)
list_status_var = tk.StringVar(value="Result: 0")
tk.Label(
    status_bar,
    textvariable=list_status_var,
    foreground="dark green",
    anchor="e",
).pack(side="right", padx=5, pady=1)

# Left buttons (operators)
left_bar = tk.Frame(bottom_bar)
left_bar.pack(side="left", padx=4)

def make_function_button(parent, text, command):
    """Create a button whose placeholder x is dark gray."""
    if "x" not in text:
        button = tk.Button(parent, text=text, width=3, command=command)
        button.pack(side="left", padx=1, pady=2)
        return button

    # A normal Tk button supports only one text color, so use a small
    # button-like frame containing separately colored character labels.
    style_source = tk.Button(parent)
    button_bg = style_source.cget("background")
    button_fg = style_source.cget("foreground")
    button_font = style_source.cget("font")
    style_source.destroy()

    measured_font = tkfont.Font(font=button_font)
    button = tk.Frame(
        parent,
        width=measured_font.measure("000") + 14,
        height=measured_font.metrics("linespace") + 10,
        background=button_bg,
        borderwidth=2,
        relief="raised",
    )
    button.pack(side="left", padx=1, pady=2)
    button.pack_propagate(False)

    label_row = tk.Frame(button, background=button_bg)
    label_row.place(relx=0.5, rely=0.5, anchor="center")
    clickable_widgets = [button, label_row]

    for character in text:
        label = tk.Label(
            label_row,
            text=character,
            font=button_font,
            foreground="#808080" if character == "x" else button_fg,
            background=button_bg,
            borderwidth=0,
            padx=0,
            pady=0,
        )
        label.pack(side="left")
        clickable_widgets.append(label)

    def press(event=None):
        button.config(relief="sunken")
        button.grab_set()

    def release(event=None):
        button.config(relief="raised")
        try:
            button.grab_release()
        except tk.TclError:
            pass

        pointer_x = button.winfo_pointerx() - button.winfo_rootx()
        pointer_y = button.winfo_pointery() - button.winfo_rooty()
        if 0 <= pointer_x < button.winfo_width() and 0 <= pointer_y < button.winfo_height():
            command()

    for widget in clickable_widgets:
        widget.bind("<ButtonPress-1>", press)
        widget.bind("<ButtonRelease-1>", release)

    return button


function_buttons = [
    ("Ans", lambda: insert_text("ANS")),
    ("(x)", insert_parentheses),
    ("x^", lambda: apply_to_selection_or_insert("", "^", "^")),
    ("x⁻¹", lambda: apply_to_selection_or_insert("", "^(-1)", "^(-1)")),
    ("x²", lambda: apply_to_selection_or_insert("", "²", "²")),
    ("√x", lambda: apply_to_selection_or_insert("√", "", "√(")),
    ("π", lambda: insert_text("π")),
]

for label, action in function_buttons:
    make_function_button(left_bar, label, action)

digit_status_var = tk.StringVar(value=f"Digits: {MAX_DIGITS}")
digit_status_label = tk.Label(
    left_bar,
    textvariable=digit_status_var,
    foreground="#606060",
    cursor="hand2",
    padx=5,
)
digit_status_label.pack(side="left", padx=(4, 1), pady=2)
digit_status_label.bind("<Button-1>", show_right_click_menu)
digit_status_label.bind("<Button-3>", show_right_click_menu)

# Right buttons (actions)
right_bar = tk.Frame(bottom_bar)
right_bar.pack(side="right", padx=4)
#tk.Button(right_bar, text="↑", width=4, height=1, command=increase_font).pack(side="left", padx=1)
#tk.Button(right_bar, text="↓", width=4, height=1, command=decrease_font).pack(side="left", padx=1)
#tk.Button(right_bar, text="Copy", width=4, command=copy_text).pack(side="left", padx=1)
tk.Button(right_bar, text="C", width=3, command=clear_screen).pack(side="left", padx=1)
btn_top = tk.Button(right_bar, text="📌", width=3, command=toggle_topmost)
btn_top.pack(side="left", padx=1)

keypad_layout = (
    (("7", "7"), ("8", "8"), ("9", "9"), ("÷", "/")),
    (("4", "4"), ("5", "5"), ("6", "6"), ("×", "*")),
    (("1", "1"), ("2", "2"), ("3", "3"), ("−", "-")),
    (("0", "0"), (".", "."), ("=", "="), ("+", "+")),
)

for column in range(4):
    keypad_frame.grid_columnconfigure(column, weight=1, uniform="keypad")

for row, keys in enumerate(keypad_layout):
    keypad_frame.grid_rowconfigure(row, weight=1)
    for column, (label, value) in enumerate(keys):
        if value == "=":
            command = evaluate_expression
        elif value in "+-*/":
            command = lambda operator=value: insert_keypad_operator(operator)
        else:
            command = lambda text=value: insert_text(text)

        tk.Button(
            keypad_frame,
            text=label,
            command=command,
            takefocus=False,
        ).grid(
            row=row,
            column=column,
            sticky="nsew",
            padx=1,
            pady=1,
        )

frame = tk.Frame(root)
frame.pack(fill="both", expand=True)

# Drag window from anywhere
frame.bind("<ButtonPress-1>", start_window_move, add="+")
frame.bind("<B1-Motion>", do_window_move, add="+")

bottom_bar.bind("<ButtonPress-1>", start_window_move, add="+")
bottom_bar.bind("<B1-Motion>", do_window_move, add="+")

status_bar.bind("<ButtonPress-1>", start_window_move, add="+")
status_bar.bind("<B1-Motion>", do_window_move, add="+")


v_scroll = tk.Scrollbar(frame, orient="vertical")
v_scroll.pack(side="right", fill="y")
#h_scroll = tk.Scrollbar(frame, orient="horizontal")
#h_scroll.pack(side="bottom", fill="x")

calc_text = tk.Text(
    frame,
    wrap="char",
    font=("Calibri", current_font_size),
    yscrollcommand=v_scroll.set,
)



calc_text.edit_modified(False)

calc_text.pack(fill="both", expand=True)

# ---- Fix blank line at startup ----
calc_text.delete("1.0", "end-1c")   # remove any empty lines
calc_text.mark_set("insert", "1.0") # place cursor at the very beginning
calc_text.focus_set()


v_scroll.config(command=calc_text.yview)
#h_scroll.config(command=calc_text.xview)

calc_text.tag_configure("expr", foreground="black")
calc_text.tag_configure(
    "operator",
    font=("Calibri", current_font_size, "bold"),
)
calc_text.tag_configure(
    "result",
    foreground="dark green",
    font=("Calibri", current_font_size, "bold"),
    spacing3=RESULT_BOTTOM_SPACING,
)
calc_text.tag_configure(
    "invalid",
    foreground="gray60",
    font=("Calibri", current_font_size)
)
calc_text.tag_configure("list_entry")
calc_text.tag_configure(
    "list_result",
    foreground="dark green",
    font=("Calibri", current_font_size, "bold"),
    spacing3=RESULT_BOTTOM_SPACING,
)
fraction_size = max(8, current_font_size - 3)
calc_text.tag_configure("fraction", font=("Calibri", fraction_size))
calc_text.tag_configure(
    "result_fraction",
    font=("Calibri", fraction_size, "bold"),
)


calc_text.bind("<Return>", evaluate_expression, add="+")
#calc_text.bind("<Return>", lambda e: format_number_at_cursor(calc_text))
#calc_text.bind("<Escape>", lambda e: clear_screen())
calc_text.bind("<Escape>", handle_escape)
calc_text.bind("<KeyPress>", handle_keypress)
root.bind("<Control-MouseWheel>", handle_ctrl_mousewheel)
calc_text.bind("<Control-KeyPress>", handle_control_shortcut)
calc_text.bind("<<Modified>>", on_text_modified)
calc_text.bind("<Button-3>", show_right_click_menu)
calc_text.bind("<FocusIn>", restore_selection_cursor_on_focus, add="+")
calc_text.bind(
    "<ButtonRelease-1>",
    lambda event: calc_text.after_idle(update_list_status),
    add="+",
)
calc_text.bind(
    "<KeyRelease>",
    lambda event: calc_text.after_idle(update_list_status),
    add="+",
)

# Create right-click menu
#precision_menu = tk.Menu(root, tearoff=0)
#precision_menu.add_command(label="Digits: 0", command=lambda: set_digits(0))
#precision_menu.add_command(label="Digits: 1", command=lambda: set_digits(1))
#precision_menu.add_command(label="Digits: 2", command=lambda: set_digits(2))
#precision_menu.add_command(label="Digits: 3", command=lambda: set_digits(3))
#precision_menu.add_command(label="Digits: 4", command=lambda: set_digits(4))
#precision_menu.add_command(label="Digits: 12", command=lambda: set_digits(12))


load_state()  # <--- load geometry before showing window
root.update_idletasks()
root.deiconify()

# ------------------------------
# RIGHT-CLICK MENU SETUP (Part 2)
# ------------------------------
right_click_menu = tk.Menu(root, tearoff=0)

digit_options = [0, 1, 2, 3, 4, 12]
digit_vars = {}

for d in digit_options:
    var = tk.IntVar(value=1 if MAX_DIGITS == d else 0)
    digit_vars[d] = var
    right_click_menu.add_radiobutton(
        label=f"{d} digits",
        variable=var,
        value=1,
        command=lambda sel=d: set_digits(sel)
    )

right_click_menu.add_separator()
separator_menu = tk.Menu(right_click_menu, tearoff=0)
digit_separator_var = tk.StringVar(value=digit_separator)
for separator_label, separator_value in (
    ("Comma (,)", ","),
    ("Apostrophe (')", "'"),
):
    separator_menu.add_radiobutton(
        label=separator_label,
        variable=digit_separator_var,
        value=separator_value,
        command=lambda value=separator_value: set_digit_separator(value),
    )
right_click_menu.add_cascade(
    label="Digit Separator",
    menu=separator_menu,
)

live_formatting_var = tk.BooleanVar(value=live_formatting_enabled)
right_click_menu.add_checkbutton(
    label="Live Number Formatting",
    variable=live_formatting_var,
    command=toggle_live_formatting
)

pretty_operators_var = tk.BooleanVar(value=pretty_operators_enabled)
right_click_menu.add_checkbutton(
    label="Use × and ÷ Symbols",
    variable=pretty_operators_var,
    command=toggle_pretty_operators,
)

list_mode_var = tk.BooleanVar(value=list_mode_enabled)
right_click_menu.add_checkbutton(
    label="List Mode",
    variable=list_mode_var,
    command=toggle_list_mode,
)
keypad_visible_var = tk.BooleanVar(value=keypad_visible)
right_click_menu.add_checkbutton(
    label="Show Keypad",
    variable=keypad_visible_var,
    command=toggle_keypad,
)
right_click_menu.add_separator()
right_click_menu.add_command(label="Copy", command=lambda: copy_text())
right_click_menu.add_command(label="Paste", command=lambda: paste_text())


update_list_mode_ui(prepare_input=False)



# set cursor after loading
calc_text.mark_set("insert", "end-1c")
calc_text.see("end-1c")
calc_text.focus_set()


root.after_idle(start_tray_icon)


#root.after(100, calc_text.focus_set)
root.mainloop()
