import requests
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse, QueryDict
from django.shortcuts import redirect
from django.template import RequestContext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_GET

from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.helpers import render_authentication_error
from allauth.socialaccount.models import SocialLogin
from allauth.socialaccount import app_settings, providers

from sumo.urlresolvers import reverse

from .provider import PersonaProvider


@never_cache
@require_GET
def persona_csrf(request):
    """Fetch a CSRF token for the frontend JavaScript."""
    # Bluntly stolen from django-browserid

    # Different CSRF libraries (namely session_csrf) store the CSRF
    # token in different places. The only way to retrieve the token
    # that works with both the built-in CSRF and session_csrf is to
    # pull it from the template context processors via
    # RequestContext.
    context = RequestContext(request)

    # csrf_token might be a lazy value that triggers side-effects,
    # so we need to force it to a string.
    csrf_token = unicode(context.get('csrf_token', ''))

    return HttpResponse(csrf_token)


@require_POST
def persona_login(request):
    """
    This is a view to work around an optimization in the Zeus load balancer
    that doesn't allow creating session cookies on the frontpage.

    We're stash the Persona assertion in the session and trigger setting
    the session cookie by that. We then redirect to the real persona login
    view called "persona_complete" to complete the Perona steps.
    """
    # REDFLAG FIXME TODO GODDAMNIT
    request.session['sociallogin_assertion'] = request.POST.get('assertion', '')
    querystring = QueryDict('', mutable=True)
    for param in ('next', 'process'):
        querystring[param] = request.POST.get(param, '')
    return redirect('%s?%s' % (reverse('persona_complete'),
                               querystring.urlencode('/')))


def persona_complete(request):
    assertion = request.session.pop('sociallogin_assertion', '')
    settings = app_settings.PROVIDERS.get(PersonaProvider.id, {})
    audience = settings.get('AUDIENCE', None)
    if audience is None:
        raise ImproperlyConfigured("No Persona audience configured. Please "
                                   "add an AUDIENCE item to the "
                                   "SOCIALACCOUNT_PROVIDERS['persona'] setting.")

    resp = requests.post('https://verifier.login.persona.org/verify',
                         {'assertion': assertion,
                          'audience': audience})
    if resp.json()['status'] != 'okay':
        return render_authentication_error(request)
    extra_data = resp.json()
    login = providers.registry \
        .by_id(PersonaProvider.id) \
        .sociallogin_from_response(request, extra_data)
    login.state = SocialLogin.state_from_request(request)
    return complete_social_login(request, login)
