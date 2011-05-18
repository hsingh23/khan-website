import copy
import logging

import django.template as template
import django.utils.html as html
import templateext

FIRST_PASS_ENABLED = False

class TwoPassVariableDoesNotExist(Exception):
    pass

def enable_first_pass(enabled):
    global FIRST_PASS_ENABLED
    FIRST_PASS_ENABLED = enabled

# Patch up variable resolution to raise our special VariableDoesNotExist exception during first pass rendering
def patch_variable_resolution():
    resolve_var_old = template.resolve_variable

    def resolve_var_new(path, context):
        try:
            return resolve_var_old(path, context)
        except template.VariableDoesNotExist:
            if FIRST_PASS_ENABLED:
                # Throw different type of VariableDoesNotExist exception that we catch later
                raise TwoPassVariableDoesNotExist
            else:
                # Throw original exception
                raise

    template.resolve_variable = resolve_var_new

# Patch up node rendering to return raw template text version of each tag if special VariableDoesNotExist encountered
def patch_node_rendering():

    def get_new_render(old_render):
        def new_render(*args, **kw_args):
            if FIRST_PASS_ENABLED:
                try:
                    return old_render(*args, **kw_args)
                except TwoPassVariableDoesNotExist:
                    self = args[0]
                    if hasattr(self, "raw_template_text"):
                        return self.raw_template_text
                    elif isinstance(self, template.VariableNode):
                        return "{{%s}}" % self.filter_expression
                    else:
                        return ""
            else:
                return old_render(*args, **kw_args)
        return new_render

    # Patch rendering for all subclasses of Node
    subclasses = template.Node.__subclasses__()
    for subclass in subclasses:
        if not hasattr(subclass, "two_pass_patched"):
            subclass.render = get_new_render(subclass.render)
            subclass.two_pass_patched = True

# Patch up tag parsing to keep raw template text version of each tag available
def patch_tag_parsing():

    def get_new_parse(old_parse):
        def new_parse(parser, token):
            if not FIRST_PASS_ENABLED:
                return old_parse(parser, token)
            else:
                raw_template_text = raw_template_text_parse(parser, token)
                node = old_parse(parser, token)
                if node:
                    node.raw_template_text = raw_template_text
                return node
        return new_parse

    # Patch all tags
    for key in template.libraries:
        reg = template.libraries[key]
        for tag_key in reg.tags:
            old_parse = reg.tags[tag_key]
            reg.tags[tag_key] = get_new_parse(old_parse)

# Patch up HTML and JS escaping to protect against template injection
def patch_escaping():

    # Patch HTML escaping
    escape_html_old = html.escape

    def escape_html_new(value):
        v = escape_html_old(value)
        if not FIRST_PASS_ENABLED:
            return v
        else:
            return v.replace("{", "&#123;").replace("}", "&#125;")

    html.escape = escape_html_new

    # Patch JS escaping
    templateext._js_escapes = (templateext._js_escapes + (("{", "\u007B"), ("}", "\u007D")))

patched = False
def patch():
    global patched
    if patched:
        return

    patch_variable_resolution()
    patch_node_rendering()
    patch_tag_parsing()
    patch_escaping()

    patched = True

# Get raw template text for token
# See inspiration at http://www.holovaty.com/writing/django-two-phased-rendering/
def raw_template_text_parse(parser, token):
    tag_mapping = {
        template.TOKEN_TEXT: ('', ''),
        template.TOKEN_VAR: ('{{', '}}'),
        template.TOKEN_BLOCK: ('{%', '%}'),
        template.TOKEN_COMMENT: ('{#', '#}'),
    }

    list_raw_tokens = [token]

    if token.token_type == template.TOKEN_BLOCK:

        # Store original token state for restoration since we're parsing twice
        tokens_orig = copy.copy(parser.tokens)

        token_name = list(token.split_contents())[0]
        end_token_name = 'end' + token_name
        end_stack = [end_token_name]
        list_raw_tokens_search = []

        while parser.tokens:
            token_next = parser.next_token()

            if not token_next:
                raise Exception("Missing end of block token for raw template text parser")

            list_raw_tokens_search.append(token_next)

            if token_next.token_type == template.TOKEN_BLOCK:
                if token_next.contents == end_token_name:
                    end_stack.pop()
                    if len(end_stack) <= 0:
                        break
                else:
                    token_next_name = list(token_next.split_contents())[0]
                    if token_next_name == token_name:
                        end_stack.append(end_token_name)


        if len(end_stack) <= 0:
            # Found end token
            list_raw_tokens.extend(list_raw_tokens_search)

        # Restore original token state
        parser.tokens = tokens_orig

    # Build up string of raw template content
    list_raw_text = []
    for raw_token in list_raw_tokens:
        start, end = tag_mapping[raw_token.token_type]
        list_raw_text.append('%s%s%s' % (start, raw_token.contents, end))

    return "".join(list_raw_text)

