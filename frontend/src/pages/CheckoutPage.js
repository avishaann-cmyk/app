import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { ArrowLeft, CreditCard, Truck, ShieldCheck, Lock, WhatsappLogo, User, MapPin, Receipt } from '@phosphor-icons/react';
import { motion } from 'framer-motion';
import axios from 'axios';
import { useCart } from '../contexts/CartContext';
import { useAuth } from '../contexts/AuthContext';
import AuthModal from '../components/AuthModal';
import { DEFAULT_CART_RULES, computeCartTotals, isSedgefieldLocation } from '../lib/cartTotals';
import { setPageSEO } from '../lib/seo';
import { trackEvent } from '../lib/analytics';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const BRAND_LOGO = '/Logo.jpeg';

const getSessionId = () => {
  let sessionId = localStorage.getItem('guest_session_id');
  if (!sessionId) {
    sessionId = `guest_${Math.random().toString(36).substring(2)}${Date.now().toString(36)}`;
    localStorage.setItem('guest_session_id', sessionId);
  }
  return sessionId;
};

// Province options
const PROVINCES = [
  'Western Cape',
  'Gauteng',
  'KwaZulu-Natal',
  'Eastern Cape',
  'Free State',
  'Limpopo',
  'Mpumalanga',
  'North West',
  'Northern Cape'
];

const CheckoutPage = () => {
  const navigate = useNavigate();
  const { cart, refreshCart } = useCart();
  const { isAuthenticated, user } = useAuth();
  
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [step, setStep] = useState(1); // 1: Info, 2: Shipping, 3: Payment
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [guestCheckout, setGuestCheckout] = useState(false);
  
  // Guest info
  const [guestEmail, setGuestEmail] = useState('');
  const [guestPhone, setGuestPhone] = useState('');
  
  // Shipping address
  const [address, setAddress] = useState({
    first_name: user?.first_name || '',
    last_name: user?.last_name || '',
    street: '',
    apartment: '',
    city: '',
    province: '',
    postal_code: '',
    country: 'South Africa',
    phone: ''
  });
  
  // Order options
  const [saveAddress, setSaveAddress] = useState(true);
  const [orderNotes, setOrderNotes] = useState('');
  const [isSubscription, setIsSubscription] = useState(false);
  const [subscriptionFrequency, setSubscriptionFrequency] = useState('monthly');
  const shippingDestination = `${address.city || ''} ${address.province || ''}`.trim();

  // Load saved address if available
  useEffect(() => {
    setPageSEO({
      title: 'Checkout | Cape Ember Coffee Co.',
      description: 'Secure checkout for Cape Ember Coffee Co. Review shipping, VAT, and payment before placing your order.',
      canonicalPath: '/checkout',
      image: '/assets/cape-ember/cape-ember-fynbos-lifestyle.jpeg'
    });
  }, []);

  useEffect(() => {
    if (user?.saved_addresses?.length > 0) {
      const defaultAddr = user.saved_addresses.find(a => a.is_default) || user.saved_addresses[0];
      setAddress(prev => ({ ...prev, ...defaultAddr }));
    }
    if (user?.first_name) {
      setAddress(prev => ({ 
        ...prev, 
        first_name: user.first_name,
        last_name: user.last_name || ''
      }));
    }
  }, [user]);

  // Redirect if cart is empty
  useEffect(() => {
    if (!cart.items || cart.items.length === 0) {
      navigate('/cart');
    }
  }, [cart.items, navigate]);

  const handleAddressChange = (e) => {
    const { name, value } = e.target;
    setAddress(prev => ({ ...prev, [name]: value }));
  };

  const validateStep1 = () => {
    if (!isAuthenticated && !guestCheckout) {
      trackEvent('checkout_validation_error', { step: 1, field: 'guest_checkout', reason: 'guest option not selected' });
      return false;
    }
    if (guestCheckout && (!guestEmail || !guestEmail.includes('@'))) {
      setError('Please enter a valid email address');
      trackEvent('checkout_validation_error', { step: 1, field: 'email', reason: 'invalid_email' });
      return false;
    }
    return true;
  };

  const validateStep2 = () => {
    const required = ['first_name', 'last_name', 'street', 'city', 'province', 'postal_code'];
    for (const field of required) {
      if (!address[field]) {
        setError(`Please fill in ${field.replace('_', ' ')}`);
        trackEvent('checkout_validation_error', { step: 2, field, reason: 'required_field_missing' });
        return false;
      }
    }
    return true;
  };

  const handleNextStep = () => {
    setError('');
    if (step === 1 && validateStep1()) {
      setStep(2);
    } else if (step === 2 && validateStep2()) {
      // Track shipping info when address is confirmed
      trackEvent('add_shipping_info', {
        city: address.city,
        province: address.province,
        is_sedgefield: isSedgefieldLocation(`${address.city} ${address.province}`),
      });
      trackEvent('shipping_rule_applied', {
        city: address.city,
        province: address.province,
        rule: isSedgefieldLocation(`${address.city} ${address.province}`) ? 'sedgefield_local_delivery' : 'standard_or_threshold',
      });
      if (isSedgefieldLocation(`${address.city} ${address.province}`)) {
        trackEvent('sedgefield_free_delivery_applied', { city: address.city });
      }
      setStep(3);
    }
  };

  const handleCheckout = async () => {
    if (!validateStep2()) return;

    setLoading(true);
    setError('');

    try {
      await trackEvent('begin_checkout', {
        items_count: cart.items?.length || 0,
        subtotal,
        total,
        is_guest: !isAuthenticated,
        is_subscription: isSubscription
      });

      const token = localStorage.getItem('token');
      const headers = token
        ? { Authorization: `Bearer ${token}` }
        : { 'X-Session-ID': getSessionId() };

      // Track payment method selection
      trackEvent('payment_provider_selected', {
        provider: 'payfast',
      });
      trackEvent('add_payment_info', {
        payment_type: 'payfast',
        items_count: cart.items?.length || 0,
        total,
      });

      const checkoutPayload = {
        shipping: {
          method: 'standard',
          address,
          notes: orderNotes || null
        },
        billing: {
          same_as_shipping: true,
          address: null
        },
        payment_method: 'payfast',
        coupon_code: cart.coupon_code || null,
        is_guest: !isAuthenticated,
        guest_email: isAuthenticated ? null : guestEmail,
        is_subscription: isSubscription
      };

      const checkoutRes = await axios.post(`${API}/checkout`, checkoutPayload, { headers });
      const { payment, total: payableTotal, order_id } = checkoutRes.data;

      // Keep order reference available for post-payment success handling.
      localStorage.setItem('order_id', order_id);

      if (payment?.fields?.return_url?.includes('status_token=')) {
        const token = payment.fields.return_url.split('status_token=')[1]?.split('&')[0];
        if (token) {
          localStorage.setItem(`order_status_token_${order_id}`, decodeURIComponent(token));
        }
      }

      if (!payment || payment.method !== 'payfast' || !payment.fields) {
        throw new Error('Unexpected payment response');
      }

      // Create and submit PayFast form
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = payment.action_url || `https://${payment.host}/eng/process`;

      Object.entries(payment.fields).forEach(([key, value]) => {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = key;
        input.value = value;
        form.appendChild(input);
      });

      // Guard against any client/server drift before redirecting.
      const submittedAmount = Number(payment.fields.amount || 0);
      if (Math.abs(submittedAmount - Number(payableTotal || total)) > 0.01) {
        throw new Error('Payment amount mismatch. Please refresh your cart and try again.');
      }

      document.body.appendChild(form);
      form.submit();

    } catch (err) {
      console.error('Checkout error:', err);
      const errMsg = err.response?.data?.detail || err.message || 'Checkout failed. Please try again.';
      setError(errMsg);
      trackEvent('payment_error', {
        error: errMsg,
        payment_type: 'payfast',
        total,
      });
      setLoading(false);
    }
  };

  // Calculate totals from one shared helper to keep checkout/cart consistent
  const { subtotal, discount, shipping: shippingCost, total, vat: vatAmount } = computeCartTotals(cart, {
    ...DEFAULT_CART_RULES,
    destination: shippingDestination,
  });

  const getImageUrl = (item) => item.image_url || '/placeholder-coffee.jpg';

  if (!cart.items || cart.items.length === 0) {
    return null;
  }

  return (
    <div className="min-h-screen pt-20 md:pt-24 bg-[#FDFBF7]">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <button 
            onClick={() => step > 1 ? setStep(step - 1) : navigate('/cart')}
            className="inline-flex items-center gap-2 text-[#6B5048] hover:text-[#D05C23] transition-colors"
            data-testid="back-btn"
          >
            <ArrowLeft size={18} />
            {step > 1 ? 'Back' : 'Back to Cart'}
          </button>

          <img
            src={BRAND_LOGO}
            alt="Cape Ember Coffee Co."
            className="h-9 w-9 sm:h-10 sm:w-10 rounded-full object-cover object-center border border-[#E6DCD1] bg-white"
            loading="eager"
            decoding="async"
          />
          
          {/* Progress Steps */}
          <div className="hidden sm:flex items-center gap-2">
            {['Information', 'Shipping', 'Payment'].map((label, idx) => (
              <React.Fragment key={label}>
                <div className={`flex items-center gap-2 ${step > idx ? 'text-[#D05C23]' : step === idx + 1 ? 'text-[#2C1A12]' : 'text-[#6B5048]/50'}`}>
                  <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                    step > idx ? 'bg-[#D05C23] text-white' : step === idx + 1 ? 'bg-[#2C1A12] text-white' : 'bg-[#E6DCD1] text-[#6B5048]'
                  }`}>
                    {idx + 1}
                  </span>
                  <span className="text-sm">{label}</span>
                </div>
                {idx < 2 && <div className={`w-8 h-px ${step > idx + 1 ? 'bg-[#D05C23]' : 'bg-[#E6DCD1]'}`} />}
              </React.Fragment>
            ))}
          </div>
        </div>

        {error && (
          <motion.div 
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-[#C53030]/10 border border-[#C53030]/30 text-[#C53030] px-4 py-3 mb-6"
          >
            {error}
          </motion.div>
        )}

        <div className="grid lg:grid-cols-5 gap-8 lg:gap-12">
          {/* Main Form */}
          <div className="lg:col-span-3">
            {/* Step 1: Information */}
            {step === 1 && (
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="space-y-6"
              >
                <h1 className="font-heading text-3xl text-[#2C1A12]">Contact Information</h1>
                
                {!isAuthenticated ? (
                  <div className="space-y-4">
                    <div className="p-6 bg-white border border-[#E6DCD1]">
                      <p className="text-[#6B5048] mb-4">
                        Already have an account?{' '}
                        <button 
                          onClick={() => setAuthModalOpen(true)}
                          className="text-[#D05C23] font-medium hover:underline"
                        >
                          Sign in
                        </button>{' '}
                        for a faster checkout.
                      </p>
                      
                      <div className="flex items-center gap-3 mb-6">
                        <div className="flex-1 h-px bg-[#E6DCD1]" />
                        <span className="text-[#6B5048] text-sm">or continue as guest</span>
                        <div className="flex-1 h-px bg-[#E6DCD1]" />
                      </div>
                      
                      <div className="space-y-4">
                        <div>
                          <label className="block text-sm font-medium text-[#2C1A12] mb-2">Email *</label>
                          <input
                            type="email"
                            value={guestEmail}
                            onChange={(e) => { setGuestEmail(e.target.value); setGuestCheckout(true); }}
                            className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none"
                            placeholder="your@email.com"
                            data-testid="guest-email"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-[#2C1A12] mb-2">Phone (optional)</label>
                          <input
                            type="tel"
                            value={guestPhone}
                            onChange={(e) => setGuestPhone(e.target.value)}
                            className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none"
                            placeholder="+27 81 234 5678"
                            data-testid="guest-phone"
                          />
                        </div>
                      </div>
                    </div>
                    
                    <button
                      onClick={handleNextStep}
                      disabled={!guestEmail}
                      className="btn-primary w-full"
                      data-testid="continue-to-shipping"
                    >
                      Continue to Shipping
                    </button>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="p-6 bg-white border border-[#E6DCD1]">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 bg-[#D05C23]/10 rounded-full flex items-center justify-center">
                          <User size={24} className="text-[#D05C23]" />
                        </div>
                        <div>
                          <p className="font-medium text-[#2C1A12]">{user?.first_name} {user?.last_name}</p>
                          <p className="text-[#6B5048] text-sm">{user?.email}</p>
                        </div>
                      </div>
                    </div>
                    
                    <button
                      onClick={handleNextStep}
                      className="btn-primary w-full"
                      data-testid="continue-to-shipping"
                    >
                      Continue to Shipping
                    </button>
                  </div>
                )}
              </motion.div>
            )}

            {/* Step 2: Shipping */}
            {step === 2 && (
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="space-y-6"
              >
                <h1 className="font-heading text-3xl text-[#2C1A12]">Shipping Address</h1>
                
                <div className="p-6 bg-white border border-[#E6DCD1] space-y-4">
                  <div className="grid sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-[#2C1A12] mb-2">First Name *</label>
                      <input
                        type="text"
                        name="first_name"
                        value={address.first_name}
                        onChange={handleAddressChange}
                        className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none"
                        data-testid="address-firstname"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-[#2C1A12] mb-2">Last Name *</label>
                      <input
                        type="text"
                        name="last_name"
                        value={address.last_name}
                        onChange={handleAddressChange}
                        className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none"
                        data-testid="address-lastname"
                      />
                    </div>
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-[#2C1A12] mb-2">Street Address *</label>
                    <input
                      type="text"
                      name="street"
                      value={address.street}
                      onChange={handleAddressChange}
                      className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none"
                      placeholder="123 Main Street"
                      data-testid="address-street"
                    />
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-[#2C1A12] mb-2">Apartment, suite, etc. (optional)</label>
                    <input
                      type="text"
                      name="apartment"
                      value={address.apartment}
                      onChange={handleAddressChange}
                      className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none"
                      placeholder="Apt 4B"
                    />
                  </div>
                  
                  <div className="grid sm:grid-cols-3 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-[#2C1A12] mb-2">City *</label>
                      <input
                        type="text"
                        name="city"
                        value={address.city}
                        onChange={handleAddressChange}
                        className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none"
                        placeholder="e.g. Sedgefield, George, Knysna…"
                        data-testid="address-city"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-[#2C1A12] mb-2">Province *</label>
                      <select
                        name="province"
                        value={address.province}
                        onChange={handleAddressChange}
                        className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none bg-white"
                        data-testid="address-province"
                      >
                        <option value="">Select</option>
                        {PROVINCES.map(prov => (
                          <option key={prov} value={prov}>{prov}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-[#2C1A12] mb-2">Postal Code *</label>
                      <input
                        type="text"
                        name="postal_code"
                        value={address.postal_code}
                        onChange={handleAddressChange}
                        className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none"
                        placeholder="8001"
                        data-testid="address-postal"
                      />
                    </div>
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-[#2C1A12] mb-2">Phone (for delivery updates)</label>
                    <input
                      type="tel"
                      name="phone"
                      value={address.phone}
                      onChange={handleAddressChange}
                      className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none"
                      placeholder="+27 81 234 5678"
                    />
                  </div>
                  
                  {isAuthenticated && (
                    <label className="flex items-center gap-3 cursor-pointer mt-4">
                      <input
                        type="checkbox"
                        checked={saveAddress}
                        onChange={(e) => setSaveAddress(e.target.checked)}
                        className="w-5 h-5 accent-[#D05C23]"
                      />
                      <span className="text-[#6B5048]">Save this address for future orders</span>
                    </label>
                  )}
                </div>

                {/* Shipping Method */}
                <div className="p-6 bg-white border border-[#E6DCD1]">
                  <h3 className="font-medium text-[#2C1A12] mb-4 flex items-center gap-2">
                    <Truck size={20} className="text-[#D05C23]" />
                    Shipping Method
                  </h3>
                  <div className={`p-4 border ${shippingCost === 0 ? 'border-[#2F855A] bg-[#2F855A]/5' : 'border-[#E6DCD1]'}`}>
                    <div className="flex justify-between items-center">
                      <div>
                        <span className="font-medium text-[#2C1A12]">Standard Delivery</span>
                        <p className="text-sm text-[#6B5048]">3-5 business days</p>
                      </div>
                      <span className={`font-medium ${shippingCost === 0 ? 'text-[#2F855A]' : 'text-[#2C1A12]'}`}>
                        {shippingCost === 0 ? 'Free' : `R ${shippingCost.toFixed(2)}`}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Order Notes */}
                <div className="p-6 bg-white border border-[#E6DCD1]">
                  <label className="block text-sm font-medium text-[#2C1A12] mb-2">
                    Order Notes (optional)
                  </label>
                  <textarea
                    value={orderNotes}
                    onChange={(e) => setOrderNotes(e.target.value)}
                    rows={3}
                    className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none resize-none"
                    placeholder="Special instructions for delivery..."
                    data-testid="order-notes"
                  />
                </div>

                {/* Subscription Option */}
                <div className="p-6 bg-[#D05C23]/5 border border-[#D05C23]/20">
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isSubscription}
                      onChange={(e) => setIsSubscription(e.target.checked)}
                      className="mt-1 w-5 h-5 accent-[#D05C23]"
                      data-testid="subscription-checkbox"
                    />
                    <div>
                      <span className="font-medium text-[#2C1A12]">Subscribe & Save 15%</span>
                      <p className="text-sm text-[#6B5048] mt-1">
                        Get fresh coffee delivered automatically. Cancel anytime.
                      </p>
                    </div>
                  </label>

                  {isSubscription && (
                    <div className="mt-4 ml-8">
                      <label className="block text-sm text-[#6B5048] mb-2">Delivery Frequency</label>
                      <select
                        value={subscriptionFrequency}
                        onChange={(e) => setSubscriptionFrequency(e.target.value)}
                        className="w-full px-4 py-3 border border-[#E6DCD1] focus:border-[#D05C23] focus:outline-none bg-white"
                        data-testid="subscription-frequency"
                      >
                        <option value="weekly">Every Week</option>
                        <option value="biweekly">Every 2 Weeks</option>
                        <option value="monthly">Every Month</option>
                      </select>
                    </div>
                  )}
                </div>
                
                <button
                  onClick={handleNextStep}
                  className="btn-primary w-full"
                  data-testid="continue-to-payment"
                >
                  Continue to Payment
                </button>
              </motion.div>
            )}

            {/* Step 3: Payment */}
            {step === 3 && (
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="space-y-6"
              >
                <h1 className="font-heading text-3xl text-[#2C1A12]">Payment</h1>
                
                {/* Order Review */}
                <div className="p-6 bg-white border border-[#E6DCD1]">
                  <h3 className="font-medium text-[#2C1A12] mb-4">Shipping to</h3>
                  <div className="flex items-start gap-3 text-[#6B5048]">
                    <MapPin size={20} className="text-[#D05C23] mt-0.5" />
                    <div>
                      <p>{address.first_name} {address.last_name}</p>
                      <p>{address.street}{address.apartment ? `, ${address.apartment}` : ''}</p>
                      <p>{address.city}, {address.province} {address.postal_code}</p>
                    </div>
                  </div>
                  <button 
                    onClick={() => setStep(2)}
                    className="text-[#D05C23] text-sm mt-3 hover:underline"
                  >
                    Edit
                  </button>
                </div>

                {/* Payment Method */}
                <div className="p-6 bg-white border border-[#E6DCD1]">
                  <h3 className="font-medium text-[#2C1A12] mb-4 flex items-center gap-2">
                    <CreditCard size={20} className="text-[#D05C23]" />
                    Choose a secure payment method
                  </h3>
                  <div className="space-y-3">
                    <div className="w-full text-left p-4 border border-[#D05C23] bg-[#D05C23]/5">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 bg-white border border-[#E6DCD1] flex items-center justify-center">
                          <CreditCard size={20} className="text-[#2C1A12]" />
                        </div>
                        <div>
                          <span className="font-medium text-[#2C1A12]">PayFast</span>
                          <p className="text-xs text-[#6B5048]">Pay securely by card, Instant EFT or another enabled PayFast method.</p>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="text-xs text-[#6B5048] mt-3 space-y-1">
                    <p className="flex items-center gap-1"><Lock size={14} /> Secure encrypted checkout</p>
                    <p>Payment processed by the selected provider</p>
                    <p>Order support from Cape Ember</p>
                  </div>
                </div>

                {/* Place Order Button */}
                <button
                  onClick={handleCheckout}
                  disabled={loading}
                  className="btn-primary w-full py-4 text-lg flex items-center justify-center gap-2"
                  data-testid="place-order-btn"
                >
                  {loading ? (
                    <span className="spinner border-white border-t-transparent w-6 h-6" />
                  ) : (
                    <>
                      <Lock size={20} />
                      Pay securely - R {total.toFixed(2)}
                    </>
                  )}
                </button>

                <p className="text-center text-xs text-[#6B5048]">
                  By placing this order, you agree to our{' '}
                  <Link to="/terms" className="text-[#D05C23] hover:underline">Terms & Conditions</Link>{' '}
                  and{' '}
                  <Link to="/privacy" className="text-[#D05C23] hover:underline">Privacy Policy</Link>.
                </p>
              </motion.div>
            )}
          </div>

          {/* Order Summary Sidebar */}
          <div className="lg:col-span-2">
            <div className="bg-white border border-[#E6DCD1] p-7 sticky top-28 shadow-[0_14px_40px_-34px_rgba(44,26,18,0.45)]">
              <h2 className="font-heading text-xl text-[#2C1A12] mb-6 flex items-center gap-2">
                <Receipt size={20} className="text-[#D05C23]" />
                Order Summary
              </h2>
              
              {/* Cart Items */}
              <div className="space-y-4 mb-6 max-h-64 overflow-y-auto">
                {cart.items?.map((item) => (
                  <div key={item.product_id} className="flex gap-3">
                    <div className="relative w-16 h-16 bg-[#F4EFE6] flex-shrink-0">
                      <img
                        src={getImageUrl(item)}
                        alt={item.product_name}
                        className="w-full h-full object-cover"
                      />
                      <span className="absolute -top-2 -right-2 w-5 h-5 bg-[#2C1A12] text-white text-xs rounded-full flex items-center justify-center">
                        {item.quantity}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-[#2C1A12] text-sm truncate">{item.product_name}</p>
                      {item.variant_name && (
                        <p className="text-xs text-[#6B5048]">{item.variant_name}</p>
                      )}
                    </div>
                    <span className="text-sm text-[#2C1A12]">R {(item.price * item.quantity).toFixed(2)}</span>
                  </div>
                ))}
              </div>
              
              {/* Totals */}
              <div className="space-y-3 py-4 border-t border-[#E6DCD1]">
                <div className="flex justify-between text-sm text-[#6B5048]">
                  <span>Products</span>
                  <span>R {subtotal.toFixed(2)}</span>
                </div>
                {discount > 0 && (
                  <div className="flex justify-between text-sm text-[#2F855A]">
                    <span>Discount</span>
                    <span>- R {discount.toFixed(2)}</span>
                  </div>
                )}
                <div className="flex justify-between text-sm text-[#6B5048]">
                  <span>Delivery</span>
                  <span className={shippingCost === 0 ? 'text-[#2F855A]' : ''}>
                    {shippingCost === 0 ? 'Free' : `R ${shippingCost.toFixed(2)}`}
                  </span>
                </div>
                {isSedgefieldLocation(`${address.city} ${address.province}`) && (
                  <div className="text-xs text-[#2F855A] bg-[#2F855A]/10 px-3 py-2 rounded">
                    Free local delivery — Sedgefield
                  </div>
                )}
              </div>
              
              <div className="flex justify-between py-4 border-t border-[#E6DCD1]">
                <span className="font-heading text-xl text-[#2C1A12]">Total</span>
                <span className="font-heading text-xl text-[#2C1A12]">R {total.toFixed(2)}</span>
              </div>
              <p className="text-xs text-[#6B5048] text-right -mt-2">VAT included in displayed prices</p>

              {/* Trust Badges */}
              <div className="pt-4 border-t border-[#E6DCD1] space-y-3">
                <div className="flex items-center gap-2 text-xs text-[#6B5048]">
                  <ShieldCheck size={16} className="text-[#2F855A]" />
                  Secure checkout powered by PayFast
                </div>
                <div className="flex items-center gap-2 text-xs text-[#6B5048]">
                  <Truck size={16} className="text-[#D05C23]" />
                  Small-batch roasted by trusted partners
                </div>
              </div>

              {/* WhatsApp Help */}
              <div className="mt-6 pt-4 border-t border-[#E6DCD1]">
                <a
                  href={(() => { const n = (localStorage.getItem('public_whatsapp') || '27810261618').replace(/\D/g,''); return `https://wa.me/${n}`; })()}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center gap-2 text-[#6B5048] hover:text-[#25D366] transition-colors text-sm"
                  data-testid="checkout-whatsapp"
                >
                  <WhatsappLogo size={18} />
                  Need help? Chat with us
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>

      <AuthModal 
        isOpen={authModalOpen} 
        onClose={() => setAuthModalOpen(false)} 
        initialMode="login"
      />
    </div>
  );
};

export default CheckoutPage;
