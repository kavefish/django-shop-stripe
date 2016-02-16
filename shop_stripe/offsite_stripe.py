# -*- coding: utf-8 -*-
from django.core.exceptions import ImproperlyConfigured
from django.conf import settings
from django.conf.urls import patterns, url
from django.http import HttpResponseRedirect, HttpResponseBadRequest
from django.shortcuts import render, redirect
from .forms import CardForm
from django.contrib import messages
import stripe


class StripeBackend(object):
    """
    A django-shop payment backend for the stripe service, this
    is the workhorse view. It processes what the CardForm class
    kicks back to the server.
    """
    backend_name = "Stripe"
    url_namespace = "stripe"

    def __init__(self, shop):
        self.shop = shop
        self.key = getattr(settings, 'SHOP_STRIPE_KEY', None)
        self.currency = getattr(settings, 'SHOP_STRIPE_CURRENCY', None)

    def get_urls(self):
        urlpatterns = patterns(
            '',
            url(r'^$', self.stripe_payment_view, name='stripe'),
            url(r'^success/$', self.stripe_return_successful_view,
                name='stripe_success'),
        )
        return urlpatterns

    def stripe_payment_view(self, request):
        try:
            stripe.api_key = settings.SHOP_STRIPE_PRIVATE_KEY
            pub_key = settings.SHOP_STRIPE_PUBLISHABLE_KEY
        except AttributeError:
            raise ImproperlyConfigured(
                'You must define the SHOP_STRIPE_PRIVATE_KEY'
                ' and SHOP_STRIPE_PUBLISHABLE_KEY settings'
            )
        error = None
        if request.method == 'POST':
            form = CardForm(request.POST)
            try:
                card_token = request.POST['stripeToken']
            except KeyError:
                return HttpResponseBadRequest('stripeToken not set')
            currency = getattr(settings, 'SHOP_STRIPE_CURRENCY', 'usd')
            order = self.shop.get_order(request)
            order_id = self.shop.get_order_unique_id(order)
            amount = self.shop.get_order_total(order)
            amount = str(int(amount * 100))

            # build string of order items for description
            order_items = []
            for item in order.items.iterator():
                # FIXME: if there are multiple instances of a single item, then we'll naively print its name repeatedly
                order_items.append(item.product_name)
            order_summary = ', '.join(sorted(order_items))

            shipping_address = order.shipping_address_text

            # get the user's e-mail address, depending on whether they're logged in
            if request.user.is_authenticated():
                user_email = request.user.email
            else:
                user_email = request.POST['stripeEmail']

            stripe_dict = {
                'amount': amount,
                'currency': currency,
                'card': card_token,
                'description': ": ".join([user_email, order_summary, shipping_address]),
                'receipt_email': request.POST['stripeEmail']
            }
            try:
                stripe_result = stripe.Charge.create(**stripe_dict)
            except stripe.CardError as e:
                error = e
                messages.error(request,error.message)
                self.shop.cancel_payment(
                    self.shop.get_order_for_id(order_id),
                    amount,
                    self.backend_name
                )
                return redirect(self.shop.get_cancel_url())

            else:
                self.shop.confirm_payment(
                    self.shop.get_order_for_id(order_id),
                    amount,
                    stripe_result['id'],
                    self.backend_name
                )
                return redirect(self.shop.get_finished_url())
        else:
            form = CardForm()
        return render(request, "shop_stripe/payment.html", {
            'form': form,
            'error': error,
            'STRIPE_PUBLISHABLE_KEY': pub_key,
        })

    def stripe_return_successful_view(self, request):
        return HttpResponseRedirect(self.shop.get_finished_url())
