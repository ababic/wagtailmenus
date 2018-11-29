from django.utils.translation import ugettext_lazy as _
from rest_framework.exceptions import ValidationError, NotFound
from rest_framework.views import APIView
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response


from wagtailmenus.conf import settings

from . import forms
from . import renderers
from . import serializers


class MenuGeneratorView(APIView):
    menu_class = None
    argument_form_class = None
    menu_serializer_class = None

    # argument default values
    max_levels_default = None
    use_specific_default = None
    apply_active_classes_default = True
    allow_repeating_parents_default = True
    use_absolute_page_urls_default = False

    renderer_classes = (
        renderers.BrowsableAPIWithArgumentFormRenderer,
        JSONRenderer
    )

    def get_menu_class(self):
        if self.menu_class is None:
            raise NotImplementedError(
                "For subclasses of MenuGeneratorView, you must set the "
                "'menu_class' attribute or override the "
                "get_menu_class() class method."
            )
        return self.menu_class

    def get_argument_form_class(self):
        if self.argument_form_class is None:
            raise NotImplementedError(
                "For subclasses of MenuGeneratorView, you must set the "
                "'argument_form_class' attribute or override the "
                "get_argument_form_class) class method."
            )
        return self.argument_form_class

    def get_argument_form(self, request, *args, **kwargs):
        init_kwargs = self.get_argument_form_kwargs(request)
        return self.get_argument_form_class()(**init_kwargs)

    def get_argument_form_kwargs(self, request):
        defaults = self.get_argument_form_defaults(request)
        data = defaults.copy()
        data.update(request.GET.items())
        return {
            'data': data,
            'request': request,
            'view': self,
        }

    def get_argument_form_defaults(self, request):
        return {
            'max_levels': self.max_levels_default,
            'use_specific': self.use_specific_default,
            'apply_active_classes': self.apply_active_classes_default,
            'allow_repeating_parents': self.allow_repeating_parents_default,
            'use_absolute_page_urls': self.use_absolute_page_urls_default,
        }

    def get_menu_serializer_class(self):
        if self.menu_serializer_class is None:
            raise NotImplementedError(
                "For subclasses of MenuGeneratorView, you must set the "
                "'menu_serializer_class' attribute or override the "
                "get_menu_serializer_class() class method."
            )
        return self.menu_serializer_class

    def get_menu_serializer(self, instance, *args, **kwargs):
        cls = self.get_menu_serializer_class()
        kwargs['context'] = self.get_menu_serializer_context()
        return cls(instance=instance, *args, **kwargs)

    def get_menu_serializer_context(self):
        return {
            'request': self.request,
            'format': self.format_kwarg,
            'view': self,
        }

    def get(self, request, *args, **kwargs):
        # Ensure all necessary argument values are present and valid
        form = self.get_argument_form(request, *args, **kwargs)
        self.argument_form = form

        if not form.is_valid():
            raise ValidationError(form.errors)

        # Get a menu instance using the valid data
        menu_instance = self.get_menu_instance(request, form)

        # Create a serializer for this menu instance
        menu_serializer = self.get_menu_serializer(menu_instance, *args, **kwargs)

        return Response(menu_serializer.data)

    def get_menu_instance(self, request, form):
        """
        The Menu classes themselves are responsible for getting/creating menu
        instances and preparing them for rendering. So, the role of this
        method is to bundle up all available data into a format that
        ``Menu._get_render_prepared_object()`` will understand, and call that.
        """
        data = dict(form.cleaned_data)

        # `Menu._get_render_prepared_object()`` normally recieves a
        # ``RequestContext`` object, but will accept a dictionary with a
        # similar data structure.
        dummy_context = {
            'request': request,
            'current_site': data.pop('site'),
            'wagtailmenus_vals': {
                'current_page': data.pop('current_page', None),
                'section_root': data.pop('section_root_page', None),
                'current_page_ancestor_ids': data.pop('ancestor_page_ids', ()),
            }
        }
        cls = self.get_menu_class()
        data['add_sub_menus_inline'] = True  # This should always be True
        menu_instance = cls._get_render_prepared_object(dummy_context, **data)
        if menu_instance is None:
            raise NotFound(_(
                "No {class_name} object could be found matching the supplied "
                "values.").format(class_name=cls.__name__)
            )
        return menu_instance


class MainMenuGeneratorView(MenuGeneratorView):
    """
    Returns a JSON representation of a 'main menu' (including menu items) matching the supplied arguments.
    """
    menu_class = settings.models.MAIN_MENU_MODEL
    argument_form_class = forms.MainMenuGeneratorArgumentForm
    menu_serializer_class = serializers.MainMenuSerializer


class FlatMenuGeneratorView(MenuGeneratorView):
    """
    Returns a JSON representation of a 'flat menu' (including menu items) matching the supplied arguments.
    """
    menu_class = settings.models.MAIN_MENU_MODEL
    argument_form_class = forms.FlatMenuGeneratorArgumentForm
    menu_serializer_class = serializers.FlatMenuSerializer

    # argument defaults
    fall_back_to_default_site_menus_default = True

    def get_argument_form_defaults(self, request):
        initial = super().get_argument_form_defaults(request)
        initial['fall_back_to_default_site_menus'] = self.fall_back_to_default_site_menus_default
        return initial


class ChildrenMenuGeneratorView(MenuGeneratorView):
    """
    Returns a JSON representation of a 'children menu' (including menu items) matching the supplied arguments.
    """
    menu_class = settings.objects.CHILDREN_MENU_CLASS
    argument_form_class = forms.ChildrenMenuGeneratorArgumentForm
    menu_serializer_class = serializers.ChildrenMenuSerializer

    # argument defaults
    max_levels_default = settings.DEFAULT_CHILDREN_MENU_MAX_LEVELS
    use_specific_default = settings.DEFAULT_CHILDREN_MENU_USE_SPECIFIC
    apply_active_classes_default = False


class SectionMenuGeneratorView(MenuGeneratorView):
    """
    Returns a JSON representation of a 'section menu' (including menu items) matching the supplied arguments.
    """
    menu_class = settings.objects.SECTION_MENU_CLASS
    argument_form_class = forms.SectionMenuGeneratorArgumentForm
    menu_serializer_class = serializers.SectionMenuSerializer

    # argument defaults
    max_levels_default = settings.DEFAULT_SECTION_MENU_MAX_LEVELS
    use_specific_default = settings.DEFAULT_SECTION_MENU_USE_SPECIFIC
