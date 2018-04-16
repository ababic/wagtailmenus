from __future__ import absolute_import, unicode_literals

from django.test import TestCase
from django.core.exceptions import ValidationError
from wagtail import VERSION as WAGTAIL_VERSION
if WAGTAIL_VERSION >= (2, 0):
    from wagtail.core.models import Page
else:
    from wagtail.wagtailcore.models import Page

from wagtailmenus.models import (
    ChildrenMenu, MainMenu, MainMenuItem, FlatMenu, FlatMenuItem)


class TestMenuClasses(TestCase):
    fixtures = ['test.json']

    def test_mainmenuitem_meta_settings(self):
        opts = MainMenuItem._meta
        self.assertEqual(opts.verbose_name, 'menu item')
        self.assertEqual(opts.verbose_name_plural, 'menu items')
        self.assertEqual(opts.ordering, ('sort_order',))

    def test_flatmenuitem_meta_settings(self):
        opts = FlatMenuItem._meta
        self.assertEqual(opts.verbose_name, 'menu item')
        self.assertEqual(opts.verbose_name_plural, 'menu items')
        self.assertEqual(opts.ordering, ('sort_order',))

    def test_mainmenuitem_clean_missing_link_text(self):
        menu = MainMenu.objects.get(pk=1)
        new_item = MainMenuItem(menu=menu, link_url='test/')
        self.assertRaisesMessage(
            ValidationError,
            "This field is required when linking to a custom URL",
            new_item.clean)

    def test_mainmenuitem_clean_missing_link_url(self):
        menu = MainMenu.objects.get(pk=1)
        new_item = MainMenuItem(menu=menu)
        self.assertRaisesMessage(
            ValidationError,
            "Please choose an internal page or provide a custom URL",
            new_item.clean)

    def test_mainmenuitem_clean_link_url_and_link_page(self):
        menu = MainMenu.objects.get(pk=1)
        new_item = MainMenuItem(
            menu=menu,
            link_text='Test',
            link_url='test/',
            link_page=Page.objects.get(pk=6))
        self.assertRaisesMessage(
            ValidationError,
            "Linking to both a page and custom URL is not permitted",
            new_item.clean)

    def test_mainmenuitem_str(self):
        menu = MainMenu.objects.get(pk=1)
        item_1 = menu.menu_items.first()
        self.assertEqual(item_1.__str__(), 'Home')

    def test_flatmenuitem_str(self):
        menu = FlatMenu.objects.get(handle='contact')
        item_1 = menu.menu_items.first()
        self.assertEqual(item_1.__str__(), 'Call us')

    def test_mainmenu_top_level_items(self):
        menu = MainMenu.objects.get(pk=1)
        # This menu has a `use_specific` value of 1 (AUTO)
        self.assertEqual(menu.use_specific, 1)

        # So, the top-level items it return should all just be custom links
        # or have a `link_page` that is just a vanilla Page object.
        for item in menu.top_level_items:
            self.assertTrue(item.link_page is None or type(item.link_page) is Page)

        # After being called once, top_level_options should be cached, so
        # accessing it again shouldn't trigger any database queries
        with self.assertNumQueries(0):
            for item in menu.top_level_items:
                self.assertTrue(item.link_page or item.link_url)

        # Lets change `use_specific` to 2 (TOP_LEVEL)
        menu.set_use_specific(2)

        # The above should clear the cached value, so if we call
        # top_level_items again, we should get a fresh list of specific pages
        for item in menu.top_level_items:
            self.assertTrue(item.link_page is None or type(item.link_page) is not Page)

        # Lets change `use_specific` to 0 (OFF) again
        menu.set_use_specific(0)

        # Because the work has already been done to fetch specific items, even
        # though we might not need specific items, the cached value should
        # remain in-tact, with no more queries being triggered on recall.
        with self.assertNumQueries(0):
            for item in menu.top_level_items:
                assert item.link_page is None or type(item.link_page) is not Page

    def test_mainmenu_pages_for_display(self):
        menu = MainMenu.objects.get(pk=1)
        # This menu has a `use_specific` value of 1 (AUTO)
        self.assertEqual(menu.use_specific, 1)
        # And a `max_levels` value of 2
        self.assertEqual(menu.max_levels, 2)

        # So, every page returned by `pages_for_display` should just be a
        # vanilla Page object, that is live, not expired and meant to
        # appear in menus
        for p in menu.pages_for_display:
            self.assertEqual(type(p), Page)
            self.assertTrue(p.live)
            self.assertFalse(p.expired)
            self.assertTrue(p.show_in_menus)

        # Their should be 6 pages total
        self.assertEqual(len(menu.pages_for_display), 6)

        # After being called once, pages_for_display should be cached, so
        # accessing it again shouldn't trigger any database queries
        with self.assertNumQueries(0):
            for p in menu.pages_for_display:
                self.assertTrue(p.title)

        # Lets change `use_specific` to 3 (ALWAYS)
        menu.set_use_specific(3)

        # The above should clear the cached value, so if we call
        # pages_for_display again, we should get a fresh list of specific pages
        for p in menu.pages_for_display:
            self.assertNotEqual(type(p), Page)

        # Lets change `max_levels` to 1
        menu.set_max_levels(1)

        # The above should clear the cached value, so if we call
        # pages_for_display again, we it should provide an empty queryset
        self.assertQuerysetEqual(menu.pages_for_display, Page.objects.none())

        # Lets change `max_levels` to 3
        menu.set_max_levels(3)

        # The above should cleare the cached value, and now pages_for_display
        # should reurn 12 pages total to display
        self.assertEqual(len(menu.pages_for_display), 9)

        # As with `top_level_items` Even is we set `use_specific` to a lower
        # value, the cached `pages_for_display` value will not be cleared, as
        # it specific is better than not.
        menu.set_use_specific(1)

        # Because the work has already been done to fetch specific pages, even
        # though we might not need specific items, the cached value should
        # remain in-tact, with no more queries being triggered on recall.
        with self.assertNumQueries(0):
            for p in menu.pages_for_display:
                assert type(p) is not Page

    def test_add_menu_items_for_pages(self):
        menu = MainMenu.objects.get(pk=1)
        # The current number of menu items is 6
        self.assertEqual(menu.get_menu_items_manager().count(), 6)

        # 'Superheroes' has 2 children: 'D.C. Comics' & 'Marvel Comics'
        superheroes_page = Page.objects.get(title="Superheroes")
        children_of_superheroes = superheroes_page.get_children()
        self.assertEqual(children_of_superheroes.count(), 2)

        # Use 'add_menu_items_for_pages' to add pages for the above pages
        menu.add_menu_items_for_pages(children_of_superheroes)

        # The number of menu items should now be 8
        self.assertEqual(menu.get_menu_items_manager().count(), 8)

        # Evaluate menu items to a list
        menu_items = list(menu.get_menu_items_manager().all())

        # The last item should be a link to the 'D.C. Comics' page, and the
        # sort_order on the item should be 7
        dc_item = menu_items.pop()
        self.assertEqual(dc_item.link_page.title, 'D.C. Comics')
        self.assertEqual(dc_item.sort_order, 7)

        # The '2nd to last' item should be a link to the 'Marvel Comics' page,
        # and the sort_order on the item should be 6
        marvel_item = menu_items.pop()
        self.assertEqual(marvel_item.link_page.title, 'Marvel Comics')
        self.assertEqual(marvel_item.sort_order, 6)

    # ------------------------------------------------------------------------
    # get_sub_menu_template_names()
    # ------------------------------------------------------------------------

    def test_get_sub_menu_template_names_from_setting_returns_none_if_setting_not_set(self):
        self.assertEqual(
            MainMenu.get_sub_menu_template_names_from_setting(), None
        )

    @override_settings(
        WAGTAILMENUS_DEFAULT_MAIN_MENU_SUB_MENU_TEMPLATES=utils.SUB_MENU_TEMPLATE_LIST
    )
    def test_get_sub_menu_template_names_from_setting_returns_setting_value_when_set(self):
        self.assertEqual(
            MainMenu.get_sub_menu_template_names_from_setting(),
            utils.SUB_MENU_TEMPLATE_LIST
        )

    # ------------------------------------------------------------------------
    # get_specified_sub_menu_template_name()
    # ------------------------------------------------------------------------

    def test_get_specified_sub_menu_template_name_returns_none_if_no_templates_specified(self):
        menu = self.get_random_menu_instance_with_opt_vals_set()
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=2), None
        )
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=3), None
        )
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=4), None
        )

    @override_settings(
        WAGTAILMENUS_DEFAULT_MAIN_MENU_SUB_MENU_TEMPLATES=utils.SUB_MENU_TEMPLATE_LIST
    )
    def test_get_specified_sub_menu_template_name_returns_ideal_template_if_setting_defined(self):
        menu = self.get_random_menu_instance_with_opt_vals_set()
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=2),
            utils.SUB_MENU_TEMPLATE_LIST[0]
        )
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=3),
            utils.SUB_MENU_TEMPLATE_LIST[1]
        )

    @override_settings(
        WAGTAILMENUS_DEFAULT_MAIN_MENU_SUB_MENU_TEMPLATES=utils.SINGLE_ITEM_SUB_MENU_TEMPLATE_LIST
    )
    def test_get_specified_sub_menu_template_name_returns_last_template_when_no_template_specified_for_level(self):
        menu = self.get_random_menu_instance_with_opt_vals_set()
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=2),
            utils.SUB_MENU_TEMPLATE_LIST[0]
        )
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=3),
            utils.SUB_MENU_TEMPLATE_LIST[0]
        )

    @override_settings(
        WAGTAILMENUS_DEFAULT_MAIN_MENU_SUB_MENU_TEMPLATES=utils.SINGLE_ITEM_SUB_MENU_TEMPLATE_LIST
    )
    def test_get_specified_sub_menu_template_name_value_preference_order(self):
        menu = MainMenu.objects.all().first()
        menu._option_vals = utils.make_optionvals_instance(
            sub_menu_template_name='single_template_as_option.html',
            sub_menu_template_names=('option_one.html', 'option_two.html')
        )
        menu.sub_menu_template_name = 'single_template_as_attr.html'
        menu.sub_menu_template_names = utils.SUB_MENU_TEMPLATE_LIST

        # While both 'sub_menu_template_name' and 'sub_menu_template_names' are
        # specified as option values, the 'sub_menu_template_name' value will
        # be preferred
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=4),
            'single_template_as_option.html'
        )

        # If only 'sub_menu_template_names' is specified as an option value,
        # the, that will be preferred
        menu._option_vals = utils.make_optionvals_instance(
            sub_menu_template_name=None,
            sub_menu_template_names=('option_one.html', 'option_two.html')
        )
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=4),
            'option_two.html',
        )

        # If no templates have been specified via options, the
        # 'sub_menu_template_name' attribute is preferred
        menu._option_vals = utils.make_optionvals_instance(
            sub_menu_template_name=None,
            sub_menu_template_names=None
        )
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=4),
            'single_template_as_attr.html'
        )

        # If the 'sub_menu_template_name' attribute is None, the method
        # should prefer the 'sub_menu_template_names' attribute
        menu.sub_menu_template_name = None
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=4),
            menu.sub_menu_template_names[1]
        )

        # If the 'sub_menu_template_names' attribute is None, the method
        # will then return a value from the DEFAULT_MAIN_MENU_SUB_MENU_TEMPLATES
        # setting
        menu.sub_menu_template_names = None
        self.assertEqual(
            menu._get_specified_sub_menu_template_name(level=4),
            utils.SINGLE_ITEM_SUB_MENU_TEMPLATE_LIST[0]
        )

    # ------------------------------------------------------------------------
    # get_sub_menu_template_names()
    # ------------------------------------------------------------------------

    def test_get_sub_menu_template_names_does_not_include_site_specific_templates_by_default(self):
        menu = MainMenu.objects.all().first()
        menu._contextual_vals = utils.make_contextualvals_instance(
            current_site=menu.site
        )
        result = menu.get_sub_menu_template_names()
        self.assertEqual(len(result), 5)
        for val in result:
            self.assertFalse(menu.site.hostname in val)

    @override_settings(WAGTAILMENUS_SITE_SPECIFIC_TEMPLATE_DIRS=True)
    def test_get_sub_menu_template_names_includes_site_specific_templates_if_setting_is_true_and_current_site_is_in_contextual_vals(self):
        menu = MainMenu.objects.all().first()
        menu._contextual_vals = utils.make_contextualvals_instance(
            current_site=menu.site
        )
        result = menu.get_sub_menu_template_names()
        self.assertEqual(len(result), 9)
        for val in result[:4]:
            self.assertTrue(menu.site.hostname in val)

    @override_settings(WAGTAILMENUS_SITE_SPECIFIC_TEMPLATE_DIRS=True)
    def test_get_sub_menu_template_names_does_not_include_site_specific_templates_if_current_site_not_in_contextual_vals(self):
        menu = MainMenu.objects.all().first()
        menu._contextual_vals = utils.make_contextualvals_instance(
            current_site=None
        )
        result = menu.get_sub_menu_template_names()
        self.assertEqual(len(result), 5)
        for val in result:
            self.assertTrue(menu.site.hostname not in val)

    # ------------------------------------------------------------------------
    # get_template_names()
    # ------------------------------------------------------------------------

    def test_get_template_names_does_not_include_site_specific_templates_by_default(self):
        menu = MainMenu.objects.all().first()
        menu._contextual_vals = utils.make_contextualvals_instance(
            url='/', current_site=menu.site
        )
        result = menu.get_template_names()
        self.assertEqual(len(result), 2)
        for val in result:
            self.assertFalse(menu.site.hostname in val)

    @override_settings(WAGTAILMENUS_SITE_SPECIFIC_TEMPLATE_DIRS=True)
    def test_get_template_names_includes_site_specific_templates_if_setting_is_true_and_current_site_is_in_contextual_vals(self):
        menu = MainMenu.objects.all().first()
        menu._contextual_vals = utils.make_contextualvals_instance(
            url='/', current_site=menu.site
        )
        result = menu.get_template_names()
        self.assertEqual(len(result), 4)
        for val in result[:2]:
            self.assertTrue(menu.site.hostname in val)

    @override_settings(WAGTAILMENUS_SITE_SPECIFIC_TEMPLATE_DIRS=True)
    def test_get_template_names_does_not_include_site_specific_templates_if_current_site_not_in_contextual_vals(self):
        menu = MainMenu.objects.all().first()
        menu._contextual_vals = utils.make_contextualvals_instance(
            url='/', current_site=None
        )
        result = menu.get_template_names()
        self.assertEqual(len(result), 2)
        for val in result:
            self.assertTrue(menu.site.hostname not in val)
