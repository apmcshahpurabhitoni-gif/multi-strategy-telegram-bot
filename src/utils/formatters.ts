// Indian Rupee (INR) Formatting Utilities

export function formatInr(amount: number, options?: { showSign?: boolean; compact?: boolean }): string {
  const isNegative = amount < 0;
  const absVal = Math.abs(amount);
  
  let formatted = '';
  if (options?.compact && absVal >= 10000000) {
    // Crore
    formatted = `₹${(absVal / 10000000).toFixed(2)}Cr`;
  } else if (options?.compact && absVal >= 100000) {
    // Lakh
    formatted = `₹${(absVal / 100000).toFixed(2)}L`;
  } else {
    formatted = `₹` + absVal.toLocaleString('en-IN', {
      maximumFractionDigits: 2,
      minimumFractionDigits: absVal % 1 === 0 ? 0 : 2
    });
  }

  if (isNegative) {
    return `- ${formatted}`;
  }
  if (options?.showSign && amount > 0) {
    return `+ ${formatted}`;
  }
  return formatted;
}

export function formatInrPrice(price: number): string {
  if (price < 100) {
    return `₹${price.toFixed(2)}`;
  }
  return `₹${price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}
