import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Minus, Plus, Trash, ShoppingBag, ArrowRight, Tag, Truck, Gift, X, Lock, ArrowCounterClockwise } from '@phosphor-icons/react';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';
import { useCart } from '../contexts/CartContext';
import ProductCard from '../components/ProductCard';
import AuthModal from '../components/AuthModal';
import { computeCartTotals, isSedgefieldLocation } from '../lib/cartTotals';
import { setPageSEO } from '../lib/seo';
import { trackEvent } from '../lib/analytics';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const BRAND_LOGO = '/Logo.jpeg';

// Authoritative product-ID → image mapping sourced from the same paths
// used in server.py PRODUCTS_MAP. Falls back gracefully.
const PRODUCT_IMAGES = {
  'fynbos-roast':      '/assets/cape-ember/cape-ember-fynbos-lifestyle.jpeg',
  'garden-route':      '/assets/cape-ember/cape-ember-garden-route-lifestyle.jpeg',
  'garden-route-blend':'/assets/cape-ember/cape-ember-garden-route-lifestyle.jpeg',
  'ember-reserve':     '/assets/cape-ember/cape-ember-ember-reserve-lifestyle.jpeg',
  'karoo-horizon':     '/assets/cape-ember/cape-ember-karoo-horizon-lifestyle.jpeg',
  'landscape-bundle':  '/assets/cape-ember/cape-ember-landscape-bundle-banner.jpeg',
};

const getItemImage = (item) => {
  if (item.image_url && !item.image_url.includes('placeholder')) return item.image_url;
  return PRODUCT_IMAGES[item.product_id] || '/assets/cape-ember/cape-ember-fynbos-lifestyle.jpeg';
};

const DEFAULT_CART_RULES = {
  freeShippingThreshold: 399,
  shippingCost: 75,
  vatRate: 0.15,
};

const CartPage = () => {
  const { cart, updateQuantity, removeFromCart, loading, refreshCart, applyCoupon, removeCoupon } = useCart();
  const [couponCode, setCouponCode] = useState('');
  const [couponLoading, setCouponLoading] = useState(false);
  const [couponError, setCouponError] = useState('');
  const [upsellProducts, setUpsellProducts] = useState([]);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [cartRules, setCartRules] = useState(DEFAULT_CART_RULES);

  // Fetch upsell products
  useEffect(() => {
    setPageSEO({
      title: 'Shopping Cart | Cape Ember Coffee Co.',
      description: 'Review your Cape Ember coffee cart, shipping, VAT, and total before checkout.',
      canonicalPath: '/cart',
      image: '/assets/cape-ember/cape-ember-fynbos-lifestyle.jpeg'
    });

    const fetchUpsells = async () => {
      try {
        const response = await axios.get(`${API}/products`);
        const products = response.data.products || response.data;
        // Get products not in cart
        const cartIds = cart.items?.map(i => i.product_id) || [];
        const available = products.filter(p => !cartIds.includes(p.id) && !p.is_bundle);
        setUpsellProducts(available.slice(0, 2));
      } catch (error) {
        console.error('Failed to fetch upsell products:', error);
      }
    };
    if (cart.items?.length > 0) {
      fetchUpsells();
      trackEvent('view_cart', {
        items_count: cart.items.length,
        subtotal: cart.subtotal || 0,
      });
    }
  }, [cart.items, cart.subtotal]);

  useEffect(() => {
    const fetchPublicSettings = async () => {
      try {
        const response = await axios.get(`${API}/settings/public`);
        const data = response.data || {};
        setCartRules((prev) => ({
          ...prev,
          freeShippingThreshold: Number(data.free_shipping_threshold ?? prev.freeShippingThreshold),
          shippingCost: Number(data.shipping_fee ?? prev.shippingCost),
          vatRate: Number(data.vat_rate ?? prev.vatRate),
        }));
      } catch (error) {
        console.error('Failed to load public settings:', error);
      }
    };

    fetchPublicSettings();
  }, []);

  const handleApplyCoupon = async () => {
    if (!couponCode.trim()) return;
    
    setCouponLoading(true);
    setCouponError('');
    
    try {
      await applyCoupon(couponCode);
      setCouponCode('');
    } catch (error) {
      setCouponError(error.response?.data?.detail || 'Invalid coupon code');
    } finally {
      setCouponLoading(false);
    }
  };

  const handleRemoveCoupon = async () => {
    try {
      await removeCoupon();
    } catch (error) {
      console.error('Failed to remove coupon:', error);
    }
  };

  // Use centralized totals computation so cart + checkout cannot diverge
  const { subtotal, discount, shipping: shippingCost, total } = computeCartTotals(cart, cartRules);
  const freeShippingThreshold = Number(cartRules.freeShippingThreshold || 0);
  const amountToFreeShipping = freeShippingThreshold - subtotal;
  const progressToFreeShipping = freeShippingThreshold > 0
    ? Math.min((subtotal / freeShippingThreshold) * 100, 100)
    : 100;

  if (loading) {
    return (
      <div className="min-h-screen pt-20 md:pt-24 flex items-center justify-center bg-[#FDFBF7]">
        <div className="spinner border-[#D05C23] border-t-transparent w-10 h-10" />
      </div>
    );
  }

  if (!cart.items || cart.items.length === 0) {
    return (
      <div className="min-h-screen pt-20 md:pt-24 flex flex-col items-center justify-center bg-[#FDFBF7]">
        <ShoppingBag size={56} weight="light" className="text-[#E6DCD1] mb-6" />
        <h1 className="font-heading text-4xl text-[#2C1A12] mb-3">Your Cart is Empty</h1>
        <p className="text-[#6B5048] mb-8">Looks like you haven't added anything yet.</p>
        <Link to="/shop" className="btn-primary" data-testid="continue-shopping">
          Start Shopping
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen pt-20 md:pt-24 bg-[#FDFBF7]">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {/* Header */}
        <div className="flex items-center justify-between mb-8 gap-4">
          <div className="flex items-center gap-3">
            <img
              src={BRAND_LOGO}
              alt="Cape Ember Coffee Co."
              className="h-10 w-10 sm:h-12 sm:w-12 rounded-full object-cover object-center border border-[#E6DCD1] bg-white"
              loading="eager"
              decoding="async"
            />
            <h1 className="font-heading text-4xl text-[#2C1A12]">Your Cart</h1>
          </div>
          <span className="text-[#6B5048]">{cart.items.length} {cart.items.length === 1 ? 'item' : 'items'}</span>
        </div>

        {/* Complimentary Delivery Progress */}
        {subtotal > 0 && subtotal < freeShippingThreshold && (
          <motion.div 
            className="mb-8 p-4 bg-[#F4EFE6] border border-[#E6DCD1]"
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="flex items-center gap-3 mb-3">
              <Truck size={20} className="text-[#D05C23]" />
              <span className="text-[#2C1A12] font-medium">
                Add R {amountToFreeShipping.toFixed(2)} more for complimentary delivery.
              </span>
            </div>
            <div className="w-full h-2 bg-[#E6DCD1] rounded-full overflow-hidden">
              <motion.div 
                className="h-full bg-[#D05C23]"
                initial={{ width: 0 }}
                animate={{ width: `${progressToFreeShipping}%` }}
                transition={{ duration: 0.5 }}
              />
            </div>
          </motion.div>
        )}

        {subtotal >= freeShippingThreshold && (
          <motion.div 
            className="mb-8 p-4 bg-[#2F855A]/10 border border-[#2F855A]/30"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
          >
            <div className="flex items-center gap-3">
              <Truck size={20} className="text-[#2F855A]" />
              <span className="text-[#2F855A] font-medium">
                🎉 You've unlocked complimentary delivery.
              </span>
            </div>
          </motion.div>
        )}

        <div className="grid lg:grid-cols-3 gap-8 lg:gap-12">
          {/* Cart Items */}
          <div className="lg:col-span-2 space-y-4">
            <AnimatePresence>
              {cart.items.map((item) => (
                <motion.div 
                  key={item.product_id}
                  layout
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 20, height: 0 }}
                  className="flex gap-4 sm:gap-6 p-4 sm:p-6 bg-white border border-[#E6DCD1]"
                  data-testid={`cart-item-${item.product_id}`}
                >
                  {/* Image */}
                  <Link 
                    to={`/products/${item.product_id}`}
                    className="w-20 h-20 sm:w-24 sm:h-24 flex-shrink-0 bg-[#F4EFE6] border border-[#E6DCD1] overflow-hidden"
                  >
                    <img
                      src={getItemImage(item)}
                      alt={item.product_name}
                      className="w-full h-full object-contain hover:scale-105 transition-transform"
                      loading="lazy"
                    />
                  </Link>
                  
                  {/* Details */}
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between gap-2">
                      <div>
                        <Link 
                          to={`/products/${item.product_id}`}
                          className="font-heading text-lg sm:text-xl text-[#2C1A12] hover:text-[#D05C23] transition-colors line-clamp-1"
                        >
                          {item.product_name}
                        </Link>
                        {item.variant_name && (
                          <p className="text-sm text-[#6B5048] mt-1">{item.variant_name}</p>
                        )}
                        <p className="text-[#6B5048] mt-1">R {item.price.toFixed(2)} each</p>
                      </div>
                      <button
                        onClick={() => removeFromCart(item.product_id, item.variant_id)}
                        className="text-[#6B5048] hover:text-[#C53030] transition-colors p-1"
                        data-testid={`remove-${item.product_id}`}
                        aria-label="Remove item"
                      >
                        <Trash size={20} />
                      </button>
                    </div>
                    
                    <div className="flex items-center justify-between mt-4">
                      {/* Quantity */}
                      <div className="flex items-center border border-[#E6DCD1]">
                        <button
                          onClick={() => updateQuantity(item.product_id, item.variant_id, item.quantity - 1)}
                          className="p-2 hover:bg-[#F4EFE6] transition-colors"
                          data-testid={`qty-decrease-${item.product_id}`}
                          disabled={item.quantity <= 1}
                        >
                          <Minus size={16} className={item.quantity <= 1 ? 'text-[#E6DCD1]' : ''} />
                        </button>
                        <span className="w-10 text-center font-medium text-[#2C1A12]">{item.quantity}</span>
                        <button
                          onClick={() => updateQuantity(item.product_id, item.variant_id, item.quantity + 1)}
                          className="p-2 hover:bg-[#F4EFE6] transition-colors"
                          data-testid={`qty-increase-${item.product_id}`}
                        >
                          <Plus size={16} />
                        </button>
                      </div>
                      
                      {/* Line Total */}
                      <span className="font-heading text-xl text-[#2C1A12]">
                        R {(item.price * item.quantity).toFixed(2)}
                      </span>
                    </div>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>

            {/* Coupon Code */}
            <div className="p-6 bg-white border border-[#E6DCD1]">
              <div className="flex items-center gap-2 mb-4">
                <Tag size={20} className="text-[#D05C23]" />
                <span className="font-medium text-[#2C1A12]">Have a coupon?</span>
              </div>
              
              {cart.coupon_code ? (
                <div className="flex items-center justify-between bg-[#2F855A]/10 p-3 border border-[#2F855A]/30">
                  <div className="flex items-center gap-2">
                    <Tag size={18} className="text-[#2F855A]" />
                    <span className="text-[#2F855A] font-medium">{cart.coupon_code}</span>
                    <span className="text-[#2F855A]">applied</span>
                  </div>
                  <button
                    onClick={handleRemoveCoupon}
                    className="text-[#6B5048] hover:text-[#C53030] transition-colors"
                  >
                    <X size={18} />
                  </button>
                </div>
              ) : (
                <div className="flex gap-3">
                  <input
                    type="text"
                    value={couponCode}
                    onChange={(e) => setCouponCode(e.target.value.toUpperCase())}
                    placeholder="Enter coupon code"
                    className="flex-1 px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none text-[#2C1A12] placeholder-[#6B5048]/60 uppercase"
                    data-testid="coupon-input"
                  />
                  <button
                    onClick={handleApplyCoupon}
                    disabled={couponLoading || !couponCode.trim()}
                    className="btn-secondary px-6"
                    data-testid="apply-coupon-btn"
                  >
                    {couponLoading ? (
                      <span className="spinner border-[#2C1A12] border-t-transparent w-5 h-5" />
                    ) : (
                      'Apply'
                    )}
                  </button>
                </div>
              )}
              
              {couponError && (
                <p className="text-[#C53030] text-sm mt-2">{couponError}</p>
              )}
            </div>
          </div>

          {/* Order Summary */}
          <div className="lg:col-span-1">
            <div className="bg-white border border-[#E6DCD1] p-7 sticky top-28 shadow-[0_14px_40px_-34px_rgba(44,26,18,0.45)]">
              <h2 className="font-heading text-2xl text-[#2C1A12] mb-6">Order Summary</h2>
              
              <div className="space-y-3 mb-6">
                <div className="flex justify-between text-[#6B5048]">
                  <span>Subtotal (VAT Included)</span>
                  <span>R {subtotal.toFixed(2)}</span>
                </div>
                
                {discount > 0 && (
                  <div className="flex justify-between text-[#2F855A]">
                    <span>Discount</span>
                    <span>- R {discount.toFixed(2)}</span>
                  </div>
                )}
                
                <div className="flex justify-between text-[#6B5048]">
                  <span>Shipping</span>
                  <span className={shippingCost === 0 ? 'text-[#2F855A]' : ''}>
                    {shippingCost === 0 ? 'Free' : `R ${shippingCost.toFixed(2)}`}
                  </span>
                </div>
                
                <div className="border-t border-[#E6DCD1] pt-4 flex justify-between font-heading text-2xl text-[#2C1A12]">
                  <span>Final Total</span>
                  <span>R {total.toFixed(2)}</span>
                </div>
                <p className="text-xs text-[#6B5048] text-right">VAT included in displayed prices.</p>
              </div>

              <Link 
                to="/checkout" 
                className="btn-primary w-full flex items-center justify-center gap-2 py-4"
                data-testid="proceed-to-checkout"
              >
                Proceed to Checkout
                <ArrowRight size={18} />
              </Link>

              <Link 
                to="/shop" 
                className="block text-center mt-4 text-[#6B5048] hover:text-[#D05C23] transition-colors link-underline"
              >
                Continue Shopping
              </Link>

              {/* Trust Badges */}
              <div className="mt-6 pt-6 border-t border-[#E6DCD1] grid grid-cols-2 gap-4 text-center">
                <div>
                  <Lock size={20} className="text-[#D05C23] mx-auto mb-1" />
                  <span className="text-xs text-[#6B5048]">Secure Checkout</span>
                </div>
                <div>
                  <ArrowCounterClockwise size={20} className="text-[#D05C23] mx-auto mb-1" />
                  <span className="text-xs text-[#6B5048]">30-Day Returns</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Upsell — one restrained suggestion, hidden when bundle already in cart */}
        {upsellProducts.length > 0 && !cart.items?.some(i => i.product_id === 'landscape-bundle') && (
          <div className="mt-16 pt-16 border-t border-[#E6DCD1]">
            <div className="flex items-center gap-3 mb-8">
              <Gift size={22} className="text-[#D05C23]" />
              <h2 className="font-heading text-xl text-[#2C1A12]">Complete the Journey</h2>
            </div>
            <div className="grid sm:grid-cols-2 gap-6 max-w-2xl">
              {upsellProducts.slice(0, 2).map(product => (
                <ProductCard 
                  key={product.id} 
                  product={product} 
                  onAuthRequired={() => setAuthModalOpen(true)}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      <AuthModal isOpen={authModalOpen} onClose={() => setAuthModalOpen(false)} initialMode="register" />
    </div>
  );
};

export default CartPage;
