from __future__ import absolute_import, unicode_literals

from collections import defaultdict

from django.db import models
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.template.loader import get_template, select_template
from django.utils.encoding import python_2_unicode_compatible
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from modelcluster.models import ClusterableModel
from wagtail.wagtailadmin.edit_handlers import (
    FieldPanel, MultiFieldPanel, InlinePanel)
from wagtail.wagtailcore import hooks
from wagtail.wagtailcore.models import Page

from .. import app_settings
from ..forms import FlatMenuAdminForm
from ..utils.misc import get_site_from_request


# ########################################################
# Base classes
# ########################################################

class Menu(object):
    """A base class that all other 'menu' classes should inherit from."""

    max_levels = 1
    use_specific = app_settings.USE_SPECIFIC_AUTO
    pages_for_display = None
    root_page = None  # Not relevant for all menu classes
    request = None
    menu_type = ''  # provided to hook methods
    menu_short_name = ''  # used to find templates

    @classmethod
    def get_template(cls, request, user_specified_template=''):
        if user_specified_template:
            return get_template(user_specified_template)
        return select_template(cls.get_template_names(request))

    @classmethod
    def get_template_names(cls, request):
        """Returns a list of template names / locations to search when
        rendering an instance of this class. The first template that is found
        to exist will be used, so the least specific template name should come
        last in the list"""
        template_names = []
        menu_str = cls.menu_short_name
        if app_settings.SITE_SPECIFIC_TEMPLATE_DIRS:
            site = get_site_from_request(request, fallback_to_default=True)
            if site:
                hostname = site.hostname
                template_names.extend([
                    "menus/%s/%s/menu.html" % (hostname, menu_str),
                    "menus/%s/%s_menu.html" % (hostname, menu_str),
                ])
        template_names.extend([
            "menus/%s/menu.html" % menu_str,
            cls.get_least_specific_template_name(),
        ])
        return template_names

    @classmethod
    def get_least_specific_template_name(cls):
        """Return a string indicating the least specific template path/name to
        try when searching for a template to render an instance of this menu
        class."""
        raise NotImplementedError(
            "Subclasses of 'Menu' must define their own "
            "'get_fallback_template_name' implementation")

    @classmethod
    def get_sub_menu_template(cls, request, user_specified_template=''):
        if user_specified_template:
            return get_template(user_specified_template)
        return select_template(cls.get_sub_menu_template_names(request))

    @classmethod
    def get_sub_menu_template_names(cls, request):
        """Return a list of template paths/names to search when
        rendering a sub menu for an instance of this menu class. The first
        template that is found to exist will be used, so the least specific
        template name should come last in the list"""
        template_names = []
        menu_str = cls.menu_short_name
        if app_settings.SITE_SPECIFIC_TEMPLATE_DIRS:
            site = get_site_from_request(request, fallback_to_default=True)
            if site:
                hostname = site.hostname
                template_names.extend([
                    "menus/%s/%s/sub_menu.html" % (hostname, menu_str),
                    "menus/%s/%s_sub_menu.html" % (hostname, menu_str),
                    "menus/%s/sub_menu.html" % hostname,
                ])
        template_names.extend([
            "menus/%s/sub_menu.html" % menu_str,
            "menus/%s_sub_menu.html" % menu_str,
            cls.get_least_specific_sub_menu_template_name(),
        ])
        return template_names

    @classmethod
    def get_least_specific_sub_menu_template_name(cls):
        """Return a string indicating the last template path/name to try when
        searching for a template to render a sub menu for an instance of this
        menu class"""
        return app_settings.DEFAULT_SUB_MENU_TEMPLATE

    def clear_page_cache(self):
        try:
            del self.pages_for_display
        except AttributeError:
            pass
        try:
            del self.page_children_dict
        except AttributeError:
            pass

    def get_common_hook_kwargs(self):
        return {
            'request': self.request,
            'menu_type': self.menu_type,
            'max_levels': self.max_levels,
            'use_specific': self.use_specific,
            'menu_instance': self,
        }

    def get_base_page_queryset(self):
        qs = Page.objects.filter(
            live=True, expired=False, show_in_menus=True)
        # allow hooks to modify the queryset
        for hook in hooks.get_hooks('menus_modify_base_page_queryset'):
            kwargs = self.get_common_hook_kwargs()
            kwargs['root_page'] = self.root_page
            qs = hook(qs, **kwargs)
        return qs

    def set_max_levels(self, max_levels):
        if self.max_levels != max_levels:
            """
            Set `self.max_levels` to the supplied value and clear any cached
            attribute values set for a different `max_levels` value.
            """
            self.max_levels = max_levels
            self.clear_page_cache()

    def set_use_specific(self, use_specific):
        if self.use_specific != use_specific:
            """
            Set `self.use_specific` to the supplied value and clear some
            cached values where appropriate.
            """
            if(
                use_specific >= app_settings.USE_SPECIFIC_TOP_LEVEL and
                self.use_specific < app_settings.USE_SPECIFIC_TOP_LEVEL
            ):
                self.clear_page_cache()
                try:
                    del self.top_level_items
                except AttributeError:
                    pass

            self.use_specific = use_specific

    def set_request(self, request):
        """
        Set `self.request` to the supplied HttpRequest, so that developers can
        make use of it in subclasses
        """
        self.request = request

    @property
    def pages_for_display(self):
        raise NotImplementedError(
            "Subclasses of 'Menu' must define their own 'pages_for_display' "
            "method")

    @cached_property
    def page_children_dict(self):
        """Returns a dictionary of lists, where the keys are 'path' values for
        pages, and the value is a list of children pages for that page."""
        children_dict = defaultdict(list)
        for page in self.pages_for_display:
            children_dict[page.path[:-page.steplen]].append(page)
        return children_dict

    def get_children_for_page(self, page):
        """Return a list of relevant child pages for a given page."""
        return self.page_children_dict.get(page.path, [])

    def page_has_children(self, page):
        """Return a boolean indicating whether a given page has any relevant
        child pages."""
        return page.path in self.page_children_dict


class MenuFromRootPage(Menu):
    """A 'menu' that is instantiated with a 'root page', and whose 'menu items'
    consist solely of ancestors of that page."""

    root_page = None

    def __init__(self, root_page, max_levels, use_specific):
        self.root_page = root_page
        self.max_levels = max_levels
        self.use_specific = use_specific
        super(MenuFromRootPage, self).__init__()

    def get_pages_for_display(self):
        """Return all pages needed for rendering all sub-levels for the current
        menu"""
        pages = self.get_base_page_queryset().filter(
            depth__gt=self.root_page.depth,
            depth__lte=self.root_page.depth + self.max_levels,
            path__startswith=self.root_page.path,
        )

        # Return 'specific' page instances if required
        if self.use_specific == app_settings.USE_SPECIFIC_ALWAYS:
            return pages.specific()

        return pages

    @cached_property
    def pages_for_display(self):
        return self.get_pages_for_display()

    def get_children_for_page(self, page):
        """Return a list of relevant child pages for a given page."""
        if self.max_levels == 1:
            # If there's only a single level of pages to display, skip the
            # dict creation / lookup and just return the QuerySet result
            return self.pages_for_display
        return super(MenuFromRootPage, self).get_children_for_page(page)


class SectionMenu(MenuFromRootPage):
    menu_type = 'section_menu'  # provided to hook methods
    menu_short_name = 'section'  # used to find templates

    @classmethod
    def get_least_specific_template_name(cls):
        return app_settings.DEFAULT_SECTION_MENU_TEMPLATE


class ChildrenMenu(MenuFromRootPage):
    menu_type = 'children_menu'  # provided to hook methods
    menu_short_name = 'children'  # used to find templates

    @classmethod
    def get_least_specific_template_name(cls):
        return app_settings.DEFAULT_CHILDREN_MENU_TEMPLATE


class MenuWithMenuItems(ClusterableModel, Menu):
    """A base model class for menus who's 'menu_items' are defined by
    a set of 'menu item' model instances."""

    class Meta:
        abstract = True

    def get_base_menuitem_queryset(self):
        qs = self.get_menu_items_manager().for_display()
        # allow hooks to modify the queryset
        for hook in hooks.get_hooks('menus_modify_base_menuitem_queryset'):
            qs = hook(qs, **self.get_common_hook_kwargs())
        return qs

    @cached_property
    def top_level_items(self):
        """Return a list of menu items with link_page objects supplemented with
        'specific' pages where appropriate."""
        menu_items = self.get_base_menuitem_queryset()

        # Identify which pages to fetch for the top level items. We use
        # 'get_base_page_queryset' here, so that if that's being overridden
        # or modified by hooks, any pages being excluded there are also
        # excluded at the top level
        top_level_pages = self.get_base_page_queryset().filter(
            id__in=menu_items.values_list('link_page_id', flat=True)
        )
        if self.use_specific >= app_settings.USE_SPECIFIC_TOP_LEVEL:
            """
            The menu is being generated with a specificity level of TOP_LEVEL
            or ALWAYS, so we use PageQuerySet.specific() to fetch specific
            page instances as efficiently as possible
            """
            top_level_pages = top_level_pages.specific()

        # Evaluate the above queryset to a dictionary, using the IDs as keys
        pages_dict = {p.id: p for p in top_level_pages}

        # Now build a list to return
        menu_item_list = []
        for item in menu_items:
            if not item.link_page_id:
                menu_item_list.append(item)
                continue  # skip to next
            if item.link_page_id in pages_dict.keys():
                # Only return menu items for pages where the page was included
                # in the 'get_base_page_queryset' result
                item.link_page = pages_dict.get(item.link_page_id)
                menu_item_list.append(item)
        return menu_item_list

    def get_pages_for_display(self):
        """Return all pages needed for rendering all sub-levels for the current
        menu"""

        # Start with an empty queryset, and expand as needed
        all_pages = Page.objects.none()

        if self.max_levels == 1:
            # If no additional sub-levels are needed, return empty queryset
            return all_pages

        for item in self.top_level_items:

            if item.link_page_id:
                # Fetch a 'branch' of suitable descendants for this item and
                # add to 'all_pages'
                page_depth = item.link_page.depth
                if(
                    item.allow_subnav and
                    page_depth >= app_settings.SECTION_ROOT_DEPTH
                ):
                    all_pages = all_pages | Page.objects.filter(
                        depth__gt=page_depth,
                        depth__lt=page_depth + self.max_levels,
                        path__startswith=item.link_page.path)

        # Filter the entire queryset to include only pages suitable for display
        all_pages = all_pages & self.get_base_page_queryset()

        # Return 'specific' page instances if required
        if self.use_specific == app_settings.USE_SPECIFIC_ALWAYS:
            return all_pages.specific()

        return all_pages

    @cached_property
    def pages_for_display(self):
        return self.get_pages_for_display()

    def get_menu_items_manager(self):
        raise NotImplementedError(
            "Subclasses of 'MenuWithMenuItems' must define their own "
            "'get_menu_items_manager' method")

    def add_menu_items_for_pages(self, pagequeryset=None, allow_subnav=True):
        """Add menu items to this menu, linking to each page in `pagequeryset`
        (which should be a PageQuerySet instance)"""
        item_manager = self.get_menu_items_manager()
        item_class = item_manager.model
        item_list = []
        i = item_manager.count()
        for p in pagequeryset.all():
            item_list.append(item_class(
                menu=self, link_page=p, sort_order=i, allow_subnav=allow_subnav
            ))
            i += 1
        item_manager.bulk_create(item_list)


# ########################################################
# Abstract models
# ########################################################

@python_2_unicode_compatible
class AbstractMainMenu(MenuWithMenuItems):
    menu_type = 'main_menu'  # provided to hook methods
    menu_short_name = 'main'  # used to find templates

    site = models.OneToOneField(
        'wagtailcore.Site',
        verbose_name=_('site'),
        db_index=True,
        editable=False,
        on_delete=models.CASCADE,
        related_name="+",
    )
    max_levels = models.PositiveSmallIntegerField(
        verbose_name=_('maximum levels'),
        choices=app_settings.MAX_LEVELS_CHOICES,
        default=2,
        help_text=mark_safe(_(
            "The maximum number of levels to display when rendering this "
            "menu. The value can be overidden by supplying a different "
            "<code>max_levels</code> value to the <code>{% main_menu %}"
            "</code> tag in your templates."
        ))
    )
    use_specific = models.PositiveSmallIntegerField(
        verbose_name=_('specific page usage'),
        choices=app_settings.USE_SPECIFIC_CHOICES,
        default=app_settings.USE_SPECIFIC_AUTO,
        help_text=mark_safe(_(
            "Controls how 'specific' pages objects are fetched and used when "
            "rendering this menu. This value can be overidden by supplying a "
            "different <code>use_specific</code> value to the <code>"
            "{% main_menu %}</code> tag in your templates."
        ))
    )

    class Meta:
        abstract = True
        verbose_name = _("main menu")
        verbose_name_plural = _("main menu")

    @classmethod
    def get_for_site(cls, site):
        """Return the 'main menu' instance for the provided site"""
        instance, created = cls.objects.get_or_create(site=site)
        return instance

    @classmethod
    def get_least_specific_template_name(cls):
        return app_settings.DEFAULT_MAIN_MENU_TEMPLATE

    def __str__(self):
        return _('Main menu for %(site_name)s') % {
            'site_name': self.site.site_name or self.site
        }

    def get_menu_items_manager(self):
        try:
            return getattr(self, app_settings.MAIN_MENU_ITEMS_RELATED_NAME)
        except AttributeError:
            raise ImproperlyConfigured(
                "'%s' isn't a valid relationship name for accessing menu "
                "items from %s. Check that your "
                "`WAGTAILMENUS_MAIN_MENU_ITEMS_RELATED_NAME` setting matches "
                "the `related_name` used on your MenuItem model's "
                "`ParentalKey` field." % (
                    app_settings.MAIN_MENU_ITEMS_RELATED_NAME,
                    self.__class__.__name__
                )
            )

    panels = (
        InlinePanel(
            app_settings.MAIN_MENU_ITEMS_RELATED_NAME, label=_("menu items")
        ),
        MultiFieldPanel(
            heading=_("Advanced settings"),
            children=(FieldPanel('max_levels'), FieldPanel('use_specific')),
            classname="collapsible collapsed",
        ),
    )


@python_2_unicode_compatible
class AbstractFlatMenu(MenuWithMenuItems):
    menu_type = 'flat_menu'  # provided to hook methods
    menu_short_name = 'flat'  # used to find templates

    site = models.ForeignKey(
        'wagtailcore.Site',
        verbose_name=_('site'),
        db_index=True,
        on_delete=models.CASCADE,
        related_name='+'
    )
    title = models.CharField(
        verbose_name=_('title'),
        max_length=255,
        help_text=_("For internal reference only.")
    )
    handle = models.SlugField(
        verbose_name=_('handle'),
        max_length=100,
        help_text=_(
            "Used to reference this menu in templates etc. Must be unique "
            "for the selected site."
        )
    )
    heading = models.CharField(
        verbose_name=_('heading'),
        max_length=255,
        blank=True,
        help_text=_("If supplied, appears above the menu when rendered.")
    )
    max_levels = models.PositiveSmallIntegerField(
        verbose_name=_('maximum levels'),
        choices=app_settings.MAX_LEVELS_CHOICES,
        default=1,
        help_text=mark_safe(_(
            "The maximum number of levels to display when rendering this "
            "menu. The value can be overidden by supplying a different "
            "<code>max_levels</code> value to the <code>{% flat_menu %}"
            "</code> tag in your templates."
        ))
    )
    use_specific = models.PositiveSmallIntegerField(
        verbose_name=_('specific page usage'),
        choices=app_settings.USE_SPECIFIC_CHOICES,
        default=app_settings.USE_SPECIFIC_AUTO,
        help_text=mark_safe(_(
            "Controls how 'specific' pages objects are fetched and used when "
            "rendering this menu. This value can be overidden by supplying a "
            "different <code>use_specific</code> value to the <code>"
            "{% flat_menu %}</code> tag in your templates."
        ))
    )

    base_form_class = FlatMenuAdminForm

    class Meta:
        abstract = True
        unique_together = ("site", "handle")
        verbose_name = _("flat menu")
        verbose_name_plural = _("flat menus")

    @classmethod
    def get_for_site(cls, handle, site,
                     fall_back_to_default_site_menus=False):
        """Get a FlatMenu instance with a matching `handle` for the `site`
        provided - or for the 'default' site if not found."""
        menu = cls.objects.filter(handle__exact=handle, site=site).first()
        if(
            menu is None and fall_back_to_default_site_menus and
            not site.is_default_site
        ):
            return cls.objects.filter(
                handle__exact=handle, site__is_default_site=True
            ).first()
        return menu

    @classmethod
    def get_least_specific_template_name(cls):
        return app_settings.DEFAULT_FLAT_MENU_TEMPLATE

    def __str__(self):
        return '%s (%s)' % (self.title, self.handle)

    def get_menu_items_manager(self):
        try:
            return getattr(self, app_settings.FLAT_MENU_ITEMS_RELATED_NAME)
        except AttributeError:
            raise ImproperlyConfigured(
                "'%s' isn't a valid relationship name for accessing menu "
                "items from %s. Check that your "
                "`WAGTAILMENUS_FLAT_MENU_ITEMS_RELATED_NAME` setting matches "
                "the `related_name` used on your MenuItem model's "
                "`ParentalKey` field." % (
                    app_settings.FLAT_MENU_ITEMS_RELATED_NAME,
                    self.__class__.__name__
                )
            )

    def get_template(self, request, user_specified_template=''):
        if user_specified_template:
            return get_template(user_specified_template)
        return select_template(self.get_template_names(request))

    def get_template_names(self, request):
        """Returns a list of template names to search for when rendering a
        a specific flat menu object (making use of self.handle)"""
        template_names = []
        if app_settings.SITE_SPECIFIC_TEMPLATE_DIRS:
            site = get_site_from_request(request, fallback_to_default=True)
            if site:
                hostname = site.hostname
                template_names.extend([
                    "menus/%s/flat/%s/menu.html" % (hostname, self.handle),
                    "menus/%s/flat/%s.html" % (hostname, self.handle),
                    "menus/%s/%s/menu.html" % (hostname, self.handle),
                    "menus/%s/%s.html" % (hostname, self.handle),
                    "menus/%s/flat/menu.html" % hostname,
                    "menus/%s/flat/default.html" % hostname,
                    "menus/%s/flat_menu.html" % hostname,
                ])
        template_names.extend([
            "menus/flat/%s/menu.html" % self.handle,
            "menus/flat/%s.html" % self.handle,
            "menus/%s/menu.html" % self.handle,
            "menus/%s.html" % self.handle,
            "menus/flat/default.html",
            "menus/flat/menu.html",
            self.get_least_specific_template_name(),
        ])
        return template_names

    def get_sub_menu_template(self, request, user_specified_template=''):
        if user_specified_template:
            return get_template(user_specified_template)
        return select_template(self.get_sub_menu_template_names(request))

    def get_sub_menu_template_names(self, request):
        """Returns a list of template names to search for when rendering a
        a sub menu for a specific flat menu object (making use of self.handle)
        """
        template_names = []
        if app_settings.SITE_SPECIFIC_TEMPLATE_DIRS:
            site = get_site_from_request(request, fallback_to_default=True)
            if site:
                hostname = site.hostname
                template_names.extend([
                    "menus/%s/flat/%s/sub_menu.html" % (hostname, self.handle),
                    "menus/%s/flat/%s_sub_menu.html" % (hostname, self.handle),
                    "menus/%s/%s/sub_menu.html" % (hostname, self.handle),
                    "menus/%s/%s_sub_menu.html" % (hostname, self.handle),
                    "menus/%s/flat/sub_menu.html" % hostname,
                    "menus/%s/sub_menu.html" % hostname,
                ])
        template_names.extend([
            "menus/flat/%s/sub_menu.html" % self.handle,
            "menus/flat/%s_sub_menu.html" % self.handle,
            "menus/%s/sub_menu.html" % self.handle,
            "menus/%s_sub_menu.html" % self.handle,
            "menus/flat/sub_menu.html",
            self.get_least_specific_sub_menu_template_name(),
        ])
        return template_names

    def clean(self, *args, **kwargs):
        """Raise validation error for unique_together constraint, as it's not
        currently handled properly by wagtail."""

        clashes = self.__class__.objects.filter(site=self.site,
                                                handle=self.handle)
        if self.pk:
            clashes = clashes.exclude(pk__exact=self.pk)
        if clashes.exists():
            msg = _("Site and handle must create a unique combination. A menu "
                    "already exists with these same two values.")
            raise ValidationError({
                'site': [msg],
                'handle': [msg],
            })
        super(AbstractFlatMenu, self).clean(*args, **kwargs)

    panels = (
        MultiFieldPanel(
            heading=_("Settings"),
            children=(
                FieldPanel('title'),
                FieldPanel('site'),
                FieldPanel('handle'),
                FieldPanel('heading'),
            )
        ),
        InlinePanel(
            app_settings.FLAT_MENU_ITEMS_RELATED_NAME, label=_("menu items")
        ),
        MultiFieldPanel(
            heading=_("Advanced settings"),
            children=(FieldPanel('max_levels'), FieldPanel('use_specific')),
            classname="collapsible collapsed",
        ),
    )


# ########################################################
# Concrete models
# ########################################################

class MainMenu(AbstractMainMenu):
    """The default model for 'main menu' instances."""
    pass


class FlatMenu(AbstractFlatMenu):
    """The default model for 'flat menu' instances."""
    pass
