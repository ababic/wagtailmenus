from collections import defaultdict
from copy import copy

from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _
from modelcluster.models import ClusterableModel
from modelcluster.fields import ParentalKey

from wagtail.wagtailadmin.edit_handlers import (
    FieldPanel, PageChooserPanel, MultiFieldPanel, InlinePanel)
from wagtail.wagtailcore.models import Page, Orderable

from .app_settings import ACTIVE_CLASS, SECTION_ROOT_DEPTH
from .managers import MenuItemManager
from .panels import menupage_settings_panels


def create_page_map_from_qs(page_qs):
    pages = {}
    pages_children = defaultdict(list)
    for page in page_qs:
        pages[page.pk] = page
        pages_children[page.path[:-page.steplen]].append(page)
    return pages, pages_children


class MenuPage(Page):
    repeat_in_subnav = models.BooleanField(
        verbose_name=_("repeat in sub-navigation"),
        help_text=_(
            "If checked, a link to this page will be repeated alongside it's "
            "direct children when displaying a sub-navigation for this page."
        ),
        default=False,
    )
    repeated_item_text = models.CharField(
        verbose_name=_('repeated item link text'),
        max_length=255,
        blank=True,
        help_text=_(
            "e.g. 'Section home' or 'Overview'. If left blank, the page title "
            "will be used."
        )
    )

    settings_panels = menupage_settings_panels

    class Meta:
        abstract = True

    def modify_submenu_items(self, menu_items, current_page,
                             current_ancestor_ids, current_site,
                             allow_repeating_parents, apply_active_classes,
                             original_menu_tag):
        """
        Make any necessary modifications to `menu_items` and return the list
        back to the calling menu tag to render in templates. Any additional
        items added should have a `text` and `href` attribute as a minimum.

        `original_menu_tag` should be one of 'main_menu', 'section_menu' or
        'children_menu', which should be useful when extending/overriding.
        """
        if (allow_repeating_parents and menu_items and self.repeat_in_subnav):
            """
            This page should have a version of itself repeated alongside
            children in the subnav, so we create a new item and prepend it to
            menu_items.
            """
            extra = copy(self)
            setattr(extra, 'is_repeated_item', True)
            setattr(extra, 'text', self.repeated_item_text or self.title)
            setattr(extra, 'href', self.relative_url(current_site))
            active_class = ''
            if(apply_active_classes and self == current_page):
                active_class = ACTIVE_CLASS
            setattr(extra, 'active_class', active_class)
            menu_items.insert(0, extra)

        return menu_items

    def has_submenu_items(self, current_page, prefetched_children,
                          check_for_children, allow_repeating_parents,
                          original_menu_tag):
        """
        When rendering pages in a menu template a `has_children_in_menu`
        is added to each page, letting template developers know whether or not
        the item has a submenu that must be rendered.

        By default, we return a boolean indicating whether the page has child
        pages that should appear. But, if you're customising
        `modify_submenu_items` to programatically add menu items that aren't
        child pages, you can override this method to meet your needs.
        """
        if check_for_children:
            return bool(prefetched_children)
        return False


class MenuItem(models.Model):
    allow_subnav = False

    link_page = models.ForeignKey(
        'wagtailcore.Page',
        verbose_name=_('link to an internal page'),
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )
    link_url = models.CharField(
        max_length=255,
        verbose_name=_('link to a custom URL'),
        blank=True,
        null=True,
    )
    link_text = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Must be set if you wish to link to a custom URL."),
    )
    url_append = models.CharField(
        verbose_name=_("append to URL"),
        max_length=255,
        blank=True,
        help_text=(
            "Use this to optionally append a #hash or querystring to the "
            "above page's URL.")
    )

    objects = MenuItemManager()

    class Meta:
        abstract = True
        verbose_name = _("menu item")
        verbose_name_plural = _("menu items")

    @property
    def menu_text(self):
        if self.link_page:
            return self.link_text or self.link_page.title
        return self.link_text

    def clean(self, *args, **kwargs):
        super(MenuItem, self).clean(*args, **kwargs)

        if self.link_url and not self.link_text:
            raise ValidationError({
                'link_text': [
                    _("This must be set if you're linking to a custom URL."),
                ]
            })

        if not self.link_url and not self.link_page:
            raise ValidationError({
                'link_url': [
                    _("This must be set if you're not linking to a page."),
                ]
            })

        if self.link_url and self.link_page:
            raise ValidationError(_(
                "You cannot link to both a page and URL. Please review your "
                "link and clear any unwanted values."
            ))

    def __str__(self):
        return self.menu_text

    panels = (
        PageChooserPanel('link_page'),
        FieldPanel('url_append'),
        FieldPanel('link_url'),
        FieldPanel('link_text'),
        FieldPanel('allow_subnav'),
    )


class Menu(ClusterableModel):

    class Meta:
        abstract = True

    def get_all_pages(self, max_levels, use_specific):
        tree_pages = Page.objects.none()
        for item in self.menu_items.page_links_for_display().values(
            'allow_subnav', 'link_page__path', 'link_page__depth'
        ):
            page_path = item['link_page__path']
            page_depth = item['link_page__depth']
            if item['allow_subnav'] and page_depth >= SECTION_ROOT_DEPTH:
                # Get the page for this menuitem, along with any suitable
                # descendants, down to the specified depth/level
                branch_pages = Page.objects.filter(
                    path__startswith=page_path,
                    depth__lte=page_depth + (max_levels - 1))
            else:
                # This is either a homepage link or a page we don't need to
                # fetch descendants for, so just include the page itself
                branch_pages = Page.objects.filter(path__exact=page_path)
            # Add this branch / page to the full tree queryset
            tree_pages = tree_pages | branch_pages
        tree_pages = tree_pages.filter(
            live=True, expired=False, show_in_menus=True)
        if use_specific:
            return tree_pages.specific()
        return tree_pages.select_related('content_type')

    def get_page_map(self, max_levels, use_specific):
        page_qs = self.get_all_pages(max_levels, use_specific)
        return create_page_map_from_qs(page_qs)


class MainMenu(Menu):
    site = models.OneToOneField(
        'wagtailcore.Site', related_name="main_menu",
        db_index=True, editable=False, on_delete=models.CASCADE
    )

    class Meta:
        verbose_name = _("main menu")
        verbose_name_plural = _("main menu")

    @classmethod
    def get_or_create_for_site(cls, site):
        """
        Get or create MainMenu instance for the `site` provided.
        """
        instance, created = cls.objects.get_or_create(site=site)
        return instance

    def __str__(self):
        return _('Main menu for %s') % (self.site.site_name or self.site)

    panels = (
        InlinePanel('menu_items', label=_("Menu items")),
    )


class FlatMenu(Menu):
    site = models.ForeignKey(
        'wagtailcore.Site',
        related_name="flat_menus")
    title = models.CharField(
        max_length=255,
        help_text=_("For internal reference only."))
    handle = models.SlugField(
        max_length=100,
        help_text=_(
            "Used to reference this menu in templates etc. Must be unique "
            "for the selected site."))
    heading = models.CharField(
        max_length=255,
        blank=True,
        help_text=_(
            "If supplied, appears above the menu when rendered."))

    class Meta:
        unique_together = ("site", "handle")
        verbose_name = _("flat menu")
        verbose_name_plural = _("flat menus")

    @classmethod
    def get_for_site(cls, handle, site):
        """
        Get a FlatMenu instance with a matching `handle` for the `site`
        provided.
        """
        return cls.objects.filter(handle__exact=handle, site=site).first()

    def __str__(self):
        return '%s (%s)' % (self.title, self.handle)

    panels = (
        MultiFieldPanel(
            heading=_("Settings"),
            children=(
                FieldPanel('site'),
                FieldPanel('title'),
                FieldPanel('handle'),
                FieldPanel('heading'),
            )
        ),
        InlinePanel('menu_items', label=_("Menu items")),
    )


class MainMenuItem(Orderable, MenuItem):
    menu = ParentalKey('MainMenu', related_name="menu_items")
    allow_subnav = models.BooleanField(
        default=True,
        verbose_name=_("allow sub-menu for this item"),
        help_text=_(
            "NOTE: The sub-menu might not be displayed, even if checked. "
            "It depends on how the menu is used in this project's templates."
        )
    )


class FlatMenuItem(Orderable, MenuItem):
    menu = ParentalKey('FlatMenu', related_name="menu_items")
    allow_subnav = models.BooleanField(
        default=False,
        verbose_name=_("allow sub-menu for this item"),
        help_text=_(
            "NOTE: The sub-menu might not be displayed, even if checked. "
            "It depends on how the menu is used in this project's templates."
        )
    )
