const getNumberInput = (button) => {
  const control = button?.closest?.(
    ".ui-number-control, .settings-number-control",
  );
  return control?.querySelector?.('input[type="number"]') || null;
};

const getFiniteAttribute = (input, name) => {
  const value = Number(input.getAttribute(name));
  return Number.isFinite(value) ? value : null;
};

const dispatchNumberInputEvents = (input) => {
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
};

/**
 * Move a number input by one or more step values and notify Alpine bindings.
 * The same helper is used by settings and module-local number controls.
 */
export function stepNumberInput(button, delta) {
  const input = getNumberInput(button);
  const numericDelta = Number(delta);

  if (!input || !Number.isFinite(numericDelta) || numericDelta === 0) {
    return false;
  }

  const steps = Math.max(1, Math.floor(Math.abs(numericDelta)));

  try {
    if (numericDelta > 0) {
      input.stepUp(steps);
    } else {
      input.stepDown(steps);
    }
  } catch {
    const step = Number(input.getAttribute("step"));
    const increment = Number.isFinite(step) && step > 0 ? step : 1;
    const current = Number(input.value);
    const minimum = getFiniteAttribute(input, "min");
    const maximum = getFiniteAttribute(input, "max");
    const fallback = minimum ?? 0;
    let next = (Number.isFinite(current) ? current : fallback) +
      Math.sign(numericDelta) * increment * steps;

    if (minimum !== null) {
      next = Math.max(minimum, next);
    }
    if (maximum !== null) {
      next = Math.min(maximum, next);
    }
    input.value = String(next);
  }

  dispatchNumberInputEvents(input);
  return true;
}

if (typeof window !== "undefined") {
  window.stepNumberInput = stepNumberInput;
}
