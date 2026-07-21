import React, { useEffect, useState, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CheckCircle, XCircle, MessageCircle, Clock } from 'lucide-react';
import axios from 'axios';
import { useCart } from '../contexts/CartContext';
import { trackEvent } from '../lib/analytics';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const PaymentSuccessPage = () => {
  const [searchParams] = useSearchParams();
  const { refreshCart } = useCart();
  const [whatsappLink, setWhatsappLink] = useState('');
  const [orderStatus, setOrderStatus] = useState('pending'); // pending | paid | failed
  const [pollCount, setPollCount] = useState(0);
  const orderId = searchParams.get('order_id') || localStorage.getItem('order_id');
  const statusToken = searchParams.get('status_token') || (orderId ? localStorage.getItem(`order_status_token_${orderId}`) : null);

  const checkOrderStatus = useCallback(async () => {
    if (!orderId) return;
    try {
      const statusParams = statusToken ? `?status_token=${encodeURIComponent(statusToken)}` : '';
      const res = await axios.get(`${API}/orders/${orderId}/status${statusParams}`);
      const status = res.data?.payment_status || res.data?.status;
      if (status === 'complete' || status === 'paid') {
        setOrderStatus('paid');
        const purchaseKey = `purchase_tracked_${orderId}`;
        if (localStorage.getItem(purchaseKey) !== '1') {
          trackEvent('purchase', { order_id: orderId });
          localStorage.setItem(purchaseKey, '1');
        }
        refreshCart();
        localStorage.removeItem('order_id');
        localStorage.removeItem('whatsapp_link');
        localStorage.removeItem(`order_status_token_${orderId}`);
      } else if (status === 'payment_failed' || status === 'failed' || status === 'cancelled') {
        setOrderStatus('failed');
      }
    } catch {
      // silent — keep polling
    }
  }, [orderId, refreshCart, statusToken]);

  useEffect(() => {
    const link = localStorage.getItem('whatsapp_link');
    if (link) setWhatsappLink(link);
    checkOrderStatus();
  }, [checkOrderStatus]);

  useEffect(() => {
    if (orderStatus !== 'paid' && pollCount < 10) {
      const timer = setTimeout(() => {
        setPollCount(c => c + 1);
        checkOrderStatus();
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [pollCount, orderStatus, checkOrderStatus]);

  if (orderStatus === 'pending') {
    return (
      <div className="min-h-screen pt-20 md:pt-24 flex items-center justify-center">
        <div className="max-w-lg mx-auto px-4 text-center">
          <div className="w-20 h-20 mx-auto mb-6 bg-[#D05C23]/10 rounded-full flex items-center justify-center">
            <Clock size={48} className="text-[#D05C23] animate-spin" style={{animationDuration:'2s'}} />
          </div>
          <h1 className="font-heading text-4xl text-[#2D2622] mb-4">Verifying Payment</h1>
          <p className="text-[#5C534C] text-lg mb-6">Please wait while we confirm your payment. This usually takes a few seconds.</p>
          <p className="text-[#5C534C] text-sm">Do not close this page. You will be redirected automatically.</p>
          {pollCount >= 10 && (
            <div className="mt-8 bg-[#F2EEE8] border border-[#E5DCD0] p-6">
              <p className="text-[#5C534C] mb-4">Payment confirmation is taking longer than expected.</p>
              <p className="text-[#5C534C] text-sm">If you completed payment, your order will be confirmed shortly. Contact us at <a href="mailto:hello@capeembercoffee.co.za" className="text-[#D05C23]">hello@capeembercoffee.co.za</a> if you need assistance.</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (orderStatus === 'failed') {
    return (
      <div className="min-h-screen pt-20 md:pt-24 flex items-center justify-center">
        <div className="max-w-lg mx-auto px-4 text-center">
          <div className="w-20 h-20 mx-auto mb-6 bg-[#D32F2F]/10 rounded-full flex items-center justify-center">
            <XCircle size={48} className="text-[#D32F2F]" />
          </div>
          <h1 className="font-heading text-4xl text-[#2D2622] mb-4">Payment Not Confirmed</h1>
          <p className="text-[#5C534C] text-lg mb-8">We could not confirm your payment. Your cart has been retained.</p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link to="/checkout" className="btn-primary">Try Again</Link>
            <Link to="/cart" className="btn-secondary">Return to Cart</Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen pt-20 md:pt-24 flex items-center justify-center">
      <div className="max-w-lg mx-auto px-4 text-center animate-scale-in">
        <div className="w-20 h-20 mx-auto mb-6 bg-[#388E3C]/10 rounded-full flex items-center justify-center">
          <CheckCircle size={48} className="text-[#388E3C]" />
        </div>
        
        <h1 className="font-heading text-4xl text-[#2D2622] mb-4">Thank You!</h1>
        
        <p className="text-[#5C534C] text-lg mb-2">Your order has been confirmed.</p>
        
        {orderId && (
          <p className="text-[#5C534C] mb-6">
            Order ID: <span className="font-mono font-semibold">{orderId.slice(0, 8)}</span>
          </p>
        )}

        <div className="bg-[#F2EEE8] border border-[#E5DCD0] p-6 mb-8">
          <p className="text-[#5C534C] mb-4">
            We'll send you a confirmation email with your order details and tracking information.
          </p>
          
          {whatsappLink && (
            <a
              href={whatsappLink}
              target="_blank"
              rel="noopener noreferrer"
              className="whatsapp-btn inline-flex items-center gap-2 px-6 py-3 font-medium"
              data-testid="order-whatsapp"
            >
              <MessageCircle size={20} />
              Send Order to WhatsApp
            </a>
          )}
        </div>

        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Link to="/account" className="btn-primary" data-testid="view-orders">View My Orders</Link>
          <Link to="/shop" className="btn-secondary" data-testid="continue-shopping">Continue Shopping</Link>
        </div>
      </div>
    </div>
  );
};

const PaymentCancelPage = () => {
  const [searchParams] = useSearchParams();
  const orderId = searchParams.get('order_id');
  const statusToken = searchParams.get('status_token') || (orderId ? localStorage.getItem(`order_status_token_${orderId}`) : null);

  useEffect(() => {
    trackEvent('payment_cancelled', {
      order_id: orderId || null
    });

    const markCancelled = async () => {
      if (!orderId) return;
      const tokenPart = statusToken ? `?status_token=${encodeURIComponent(statusToken)}` : '';
      try {
        await axios.post(`${API}/orders/${orderId}/payment/cancel${tokenPart}`);
      } catch (e) {
        // Do not block UX on cancel-state sync failures.
      }
    };

    markCancelled();
  }, [orderId, statusToken]);

  return (
    <div className="min-h-screen pt-20 md:pt-24 flex items-center justify-center">
      <div className="max-w-lg mx-auto px-4 text-center animate-scale-in">
        <div className="w-20 h-20 mx-auto mb-6 bg-[#D32F2F]/10 rounded-full flex items-center justify-center">
          <XCircle size={48} className="text-[#D32F2F]" />
        </div>
        
        <h1 className="font-heading text-4xl text-[#2D2622] mb-4">
          Payment Cancelled
        </h1>
        
        <p className="text-[#5C534C] text-lg mb-8">
          Your payment was not completed. Your cart items are still saved.
        </p>

        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Link to="/checkout" className="btn-primary" data-testid="retry-payment">
            Try Again
          </Link>
          <Link to="/cart" className="btn-secondary" data-testid="back-to-cart">
            Back to Cart
          </Link>
        </div>

        <p className="text-[#5C534C] mt-8">
          Need help?{' '}
          <a
            href={(() => { const n = (localStorage.getItem('public_whatsapp') || '27810261618').replace(/\D/g,''); return `https://wa.me/${n}`; })()}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[#A94826] hover:underline"
          >
            Chat with us on WhatsApp
          </a>
        </p>
      </div>
    </div>
  );
};

export { PaymentSuccessPage, PaymentCancelPage };
