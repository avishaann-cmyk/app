import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { useAuth } from './AuthContext';
import { trackEvent } from '../lib/analytics';

const CartContext = createContext(null);

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Get or create session ID for guest carts
const getSessionId = () => {
  let sessionId = localStorage.getItem('guest_session_id');
  if (!sessionId) {
    sessionId = 'guest_' + Math.random().toString(36).substring(2) + Date.now().toString(36);
    localStorage.setItem('guest_session_id', sessionId);
  }
  return sessionId;
};

export const CartProvider = ({ children }) => {
  const { isAuthenticated, user } = useAuth();
  const [cart, setCart] = useState({ items: [], subtotal: 0, shipping: 0, total: 0 });
  const [loading, setLoading] = useState(false);

  const getAuthHeaders = useCallback(() => {
    const token = localStorage.getItem('token');
    const headers = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    if (!isAuthenticated) {
      headers['X-Session-ID'] = getSessionId();
    }
    return headers;
  }, [isAuthenticated]);

  const fetchCart = useCallback(async () => {
    try {
      setLoading(true);
      const response = await axios.get(`${API}/cart`, {
        headers: getAuthHeaders()
      });
      setCart(response.data);
    } catch (error) {
      console.error('Failed to fetch cart:', error);
      setCart({ items: [], subtotal: 0, shipping: 0, total: 0 });
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders]);

  useEffect(() => {
    fetchCart();
  }, [fetchCart, isAuthenticated]);

  const addToCart = async (productId, quantity = 1, variantId = null) => {
    try {
      const payload = { product_id: productId, quantity };
      if (variantId) {
        payload.variant_id = variantId;
      }
      await axios.post(`${API}/cart/add`, payload, {
        headers: getAuthHeaders()
      });

      await trackEvent('add_to_cart', {
        product_id: productId,
        variant_id: variantId,
        quantity
      });

      await fetchCart();
      return true;
    } catch (error) {
      console.error('Failed to add to cart:', error);
      throw error;
    }
  };

  const updateQuantity = async (productId, variantId, quantity) => {
    try {
      // Build the item_id in the format expected by the backend
      const itemId = variantId ? `${productId}_${variantId}` : productId;
      await axios.put(`${API}/cart/items/${encodeURIComponent(itemId)}`, 
        { quantity },
        { headers: getAuthHeaders() }
      );
      await fetchCart();
    } catch (error) {
      console.error('Failed to update cart:', error);
      throw error;
    }
  };

  const removeFromCart = async (productId, variantId = null) => {
    try {
      // Build the item_id in the format expected by the backend
      const itemId = variantId ? `${productId}_${variantId}` : productId;
      await axios.delete(`${API}/cart/items/${encodeURIComponent(itemId)}`, {
        headers: getAuthHeaders()
      });
      await trackEvent('remove_from_cart', {
        product_id: productId,
        variant_id: variantId,
      });
      await fetchCart();
    } catch (error) {
      console.error('Failed to remove from cart:', error);
      throw error;
    }
  };

  const clearCart = async () => {
    try {
      await axios.delete(`${API}/cart`, {
        headers: getAuthHeaders()
      });
      await fetchCart();
    } catch (error) {
      console.error('Failed to clear cart:', error);
      throw error;
    }
  };

  const applyCoupon = async (code) => {
    try {
      const response = await axios.post(`${API}/cart/coupon`, 
        { code },
        { headers: getAuthHeaders() }
      );
      await fetchCart();
      return response.data;
    } catch (error) {
      console.error('Failed to apply coupon:', error);
      throw error;
    }
  };

  const removeCoupon = async () => {
    try {
      await axios.delete(`${API}/cart/coupon`, {
        headers: getAuthHeaders()
      });
      await fetchCart();
    } catch (error) {
      console.error('Failed to remove coupon:', error);
      throw error;
    }
  };

  const cartCount = cart.items?.reduce((sum, item) => sum + item.quantity, 0) || 0;

  return (
    <CartContext.Provider value={{ 
      cart, 
      cartCount, 
      loading, 
      addToCart, 
      updateQuantity, 
      removeFromCart, 
      clearCart,
      applyCoupon,
      removeCoupon,
      refreshCart: fetchCart 
    }}>
      {children}
    </CartContext.Provider>
  );
};

export const useCart = () => {
  const context = useContext(CartContext);
  if (!context) {
    throw new Error('useCart must be used within a CartProvider');
  }
  return context;
};
