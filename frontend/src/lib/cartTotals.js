export const DEFAULT_CART_RULES = {
  freeShippingThreshold: 399,
  shippingCost: 75,
  vatRate: 0.15,
};

const normalizeText = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').replace(/\s+/g, ' ').trim();

export const isSedgefieldLocation = (value) => {
  const normalized = normalizeText(value);
  if (!normalized) return false;
  const tokens = normalized.split(' ');
  return tokens.includes('sedgefield');
};

export const calculateIncludedVat = (amount, vatRate = DEFAULT_CART_RULES.vatRate) => {
  const safeAmount = Math.max(Number(amount || 0), 0);
  return Number((safeAmount * vatRate / (1 + vatRate)).toFixed(2));
};

export const resolveShippingCost = (subtotal, rules = DEFAULT_CART_RULES) => {
  const safeSubtotal = Math.max(Number(subtotal || 0), 0);
  if (isSedgefieldLocation(rules.destination)) {
    return 0;
  }
  if (safeSubtotal >= rules.freeShippingThreshold) {
    return 0;
  }
  return Number(rules.shippingCost || 0);
};

export const computeCartTotals = (cart, rules = DEFAULT_CART_RULES) => {
  const items = cart?.items || [];
  const subtotal = Number(
    cart?.subtotal ?? items.reduce((sum, item) => sum + Number(item.price || 0) * Number(item.quantity || 0), 0)
  );

  const discount = Number(cart?.discount ?? 0);
  const shipping = Number(cart?.shipping ?? resolveShippingCost(subtotal - discount, rules));
  const discountedSubtotal = Math.max(subtotal - discount, 0);
  const vat = Number(cart?.vat ?? calculateIncludedVat(discountedSubtotal, rules.vatRate));
  const total = Number(cart?.total ?? (discountedSubtotal + shipping));

  return {
    subtotal,
    discount,
    shipping,
    vat,
    total,
    itemCount: Number(cart?.item_count ?? items.reduce((sum, item) => sum + Number(item.quantity || 0), 0)),
  };
};
