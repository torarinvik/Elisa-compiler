"""Validate private-module visibility regression fixtures."""
import re


def check_private_visibility_fixtures(
    facts,
    INACTIVE_PUBLIC_OVERLOAD_RANK,
    INACTIVE_PUBLIC_OVERLOAD_RANK_SMOKE,
    INACTIVE_STATIC_DECLARATION,
    INACTIVE_STATIC_DECLARATION_SMOKE,
    INACTIVE_STATIC_STATEMENT,
    INACTIVE_STATIC_STATEMENT_SMOKE,
    MODULE_ALIAS_CHAIN,
    MODULE_ALIAS_CHAIN_SMOKE,
    MODULE_ALIAS_PRECEDENCE,
    MODULE_ALIAS_PRECEDENCE_SMOKE,
    MODULE_ALIAS_PRIVATE_CALL,
    MODULE_ALIAS_PRIVATE_CALL_SMOKE,
    NESTED_INACTIVE_STATIC_STATEMENT,
    NESTED_INACTIVE_STATIC_STATEMENT_SMOKE,
    SAME_LINE_IMPORT_PAIRING,
    SAME_LINE_IMPORT_PAIRING_SMOKE,
    STATIC_TRUE_IMPORT_CONTROL,
    STATIC_TRUE_IMPORT_CONTROL_SMOKE,
    UNPROVEN_PUBLIC_SIBLINGS,
    UNPROVEN_PUBLIC_SIBLINGS_SMOKE,
    call_shapes_smoke_text,
    call_shapes_text,
    compact,
    consumer_text,
    function_section,
    negative_text,
    positive_text,
    root_overloads_smoke_text,
    root_overloads_text,
    unknown_static_import_text,
):
    if not all(fragment in facts['alias_member_builder'] for fragment in (
            'semantic_import_alias_target_canonical_owner(target_row,table)',
            'canonical_target==""',
            'table.module_member_owner[member_index]!=canonical_target',
            'table.module_member_owner.push(alias_name)')):
        raise SystemExit("mirrored alias members must come from the exact canonical target")
    for setup in (facts['prepare_symbol_table'], facts['unresolved_table_setup'], facts['unresolved_references_setup']):
        if not all(fragment in setup for fragment in (
                'table.imported_modules.push(annotation.owner)ifannotation.name=="__using"andnotsemantic_import_using_row_has_alias_pair(annotation,table)',
                'semantic_import_alias_target_canonical_owner(annotation,table)',
                'table.imported_modules.push(canonical_target)ifcanonical_target!=""',
                'semantic_import_alias_is_global_winner(annotation,table)')):
            raise SystemExit("every symbol-table construction path must project only exact alias winners and canonical targets")
        definite_import_view_index = setup.find('definite_import_annotations:darray[Ast::EnumAnnotation]=table.definite_import_annotations')
        binding_metadata_index = setup.find('binding_import_metadata(definite_import_annotations,table)')
        alias_members_index = setup.find('register_using_alias_members(definite_import_annotations,table)')
        canonical_target_index = setup.find('semantic_import_alias_target_canonical_owner(annotation,table)')
        if definite_import_view_index < 0 or binding_metadata_index < 0 or alias_members_index < 0 or canonical_target_index < 0 or not (
                definite_import_view_index < binding_metadata_index < alias_members_index < canonical_target_index):
            raise SystemExit("canonical alias projections must run after binding import metadata is built")
    if not all(fragment in facts['using_alias_target'] for fragment in (
            'target_row.name=="__using_alias_target"',
            "target_row.module==alias.module",
            "target_row.line==alias.line",
            "target_row.offset==alias.offset",
            "target_count==1.usize()")) or not all(fragment in facts['alias_chain_match'] for fragment in (
            'Expr.Ident(head_name,_)',
            'head_name!=alias.owner',
            'pma_alias_target_matches_owner(annotations,candidate_owner,alias,table)',
            'pma_alias_chain_prefix_ends_at(inner,owner,end,last_name,alias,annotations,table)',
            'Expr.Scope(inner,last_name,_)')) or not all(fragment in facts['alias_chain_prefix_match'] for fragment in (
            'pma_alias_chain_ends_at(inner,owner,start-2.usize(),alias,annotations,table)')) or not all(fragment in facts['alias_target_matches_owner'] for fragment in (
            'semantic_possible_import_alias_target_prefix(candidate_owner,target,alias.module,alias.offset,table)',
            'target_prefix.knownandtarget_prefix.matchesandtarget_prefix.end==candidate_owner.len')) or not all(fragment in facts['scope_owner'] for fragment in (
            'alias.name!="__using_alias"',
            "alias.owner!=alias_name",
            "pma_import_annotation_branch_selection(alias,annotations,file,table)",
            "pma_alias_chain_ends_at(base,candidate,candidate.len,alias,annotations,table)",
            "pma_using_alias_is_shadowed(annotations,file,table,alias)",
            "notbranch.knownornotbranch.active")) or "pma_import_scope_visible(current_module,alias.module)" in facts['scope_owner'] or not all(fragment in facts['alias_precedence'] for fragment in (
            "semantic_possible_import_alias_precedes(left,right,table)")) or not all(fragment in facts['alias_shadowed'] for fragment in (
            "pma_using_alias_precedes(earlier_alias,alias,table)",
            "returntrueifnotorder.known",
            "returntrueiforder.precedes")):
        raise SystemExit("PMA must resolve exact global alias winners, preserve active-branch checks, and decline uncertain aliases")
    static_statement_walk = compact(function_section(consumer_text, "pma_walk_stmts"))
    if not all(fragment in facts['static_if_row_for_position'] for fragment in (
            "selected:mutableusize=file.static_if_lines.count",
            "file.static_if_lines[row]==position.line",
            "file.static_if_offsets[row]==position.offset",
            "returnfile.static_if_lines.countifselected<file.static_if_lines.count")) or not all(fragment in static_statement_walk for fragment in (
            'Stmt.Block(kind,clause,binding,body,block_line)',
            'ifkind=="static":',
            "pma_static_if_row_for_position(file,block_line)",
            "pma_static_if_row_selection(file,branch_row,current_module,table)",
            "continueifbranch.knownandnotbranch.selected",
            "defpma_walk_stmts(statements:darray[Ast::Stmt],file:Ast::File&",
            "pma_walk_stmts(body,file,current_module,index,annotations,table,block_bound,block_bound_types)")) or \
            "defpma_report(file:Ast::File&,expression:Ast::Expr" not in facts['private_report']:
        raise SystemExit("PMA must skip statement bodies whose static-if branch is proven inactive")
    check_private_entry = compact(function_section(consumer_text, "check_private_member_access"))
    if not all(fragment in check_private_entry for fragment in (
            "annotations:darray[Ast::EnumAnnotation]=pma_active_import_annotations(file,table)",
            "pma_build_selective_import_index(annotations,private_index)",
            'pma_walk_declarations(file.top_decls,file,"",private_index,annotations,table)')):
        raise SystemExit("private-member checking must build its import index and walk declarations from branch-filtered annotations")
    if not all(fragment in facts['public_call_sibling_rank'] for fragment in (
            "pma_argument_type_name(arguments[0],bound,bound_types)",
            "pma_symbol_has_private_marker(index,symbol)",
            "ifnotunqualified_call:continueifsymbol.module_owner!=owner",
            "pma_unqualified_candidate_module_visible(index,annotations,current_module,symbol.module_owner,member)",
            "first_parameter.name==actual_type",
            "actual_type==\"int\"and(first_parameter.kind==SemTypeKind.Intorfirst_parameter.kind==SemTypeKind.Char)",
            "symbol.module_owner==\"\"orpma_within_module(current_module,symbol.module_owner)",
            "candidate_rank<-2.usize()",
            "first_parameter.kind==SemTypeKind.Namedandfirst_parameter.name==actual_typeandpma_named_type_spelling_is_unique(table,first_parameter.name)",
            "pma_generic_parameter_identity(annotations,first_parameter.name,symbol)")) or not all(fragment in facts['candidate_module_visibility'] for fragment in (
            'candidate_module==""orpma_within_module(current_module,candidate_module)',
            "pma_imported_module_member_visible(index,annotations,current_module,candidate_module,member)")) or not all(fragment in facts['private_candidate_rank'] for fragment in (
            'actual_type=="bool"',
            "public_rank>0.usize()",
            "pma_generic_parameter_identity(annotations,first_parameter.name,symbol)")):
        raise SystemExit("private-call suppression must prove exact public formals outrank private generic candidates while ties stay fail-closed")
    if not all(fragment in facts['named_type_spelling_unique'] for fragment in (
            "symbol.name!=name",
            "type_symbol:bool=symbol.kind==SymbolKind.Structorsymbol.kind==SymbolKind.Enumorsymbol.kind==SymbolKind.Aliasor(symbol.kind==SymbolKind.Externandsymbol.opaque_extern_type)",
            "nottype_symbol",
            "returnfalseiffound",
            "found<-true",
            "returnfound")):
        raise SystemExit("named-formal ranking must fail closed when a type spelling belongs to multiple nominal declarations")
    if not all(fragment in facts['private_candidate_rank'] for fragment in (
            "public_rank>1.usize()",
            "public_rank>0.usize()")):
        raise SystemExit("direct lexical winners must outrank imported candidates before same-tier receiver specificity")
    if not all(fragment in facts['static_if_function_branch_selection'] for fragment in (
            'marker.owner!="__static_if_branch"',
            'marker.name!="__function_static_branch"',
            "marker.detail_name!=name",
            "marker.module!=symbol.module_owner",
            "marker.line!=symbol.line",
            "marker.offset!=symbol.offset",
            "pma_static_if_row_selection(file,marker.identity_id.usize(),symbol.module_owner,table,depth+1)",
            "return(true,false)ifbranch.knownandnotbranch.selected",
            "return(false,false)ifunknown")) or \
            "pma_static_if_function_branch_selection(file,member,symbol,table,0)" not in facts['public_call_sibling_rank'] or \
            "continueifnotbranch.knownornotbranch.active" not in facts['public_call_sibling_rank']:
        raise SystemExit("public overload ranking may suppress private access only for function candidates proven active by exact declaration branch markers")
    if not all(fragment in facts['argument_type_probe'] for fragment in (
            "Expr.IntLit(_,_)",
            'return"int"',
            "Expr.FloatLit(_,_)",
            'return"f64"')):
        raise SystemExit("PMA must recognize Core's untyped integer and default float receiver types before suppressing a private generic winner")
    if not all(fragment in facts['call_target_normalizer'] for fragment in (
            "Expr.Paren(inner,_)",
            "Expr.Index(object,_,_)ifpma_is_private_function_target(file,object,current_module,index,annotations,table,bound)",
            "Expr.IndexN(object,_,_)ifpma_is_private_function_target(file,object,current_module,index,annotations,table,bound)")) or not all(fragment in facts['call_index_walker'] for fragment in (
            "Expr.Index(object,argument,_)",
            "Expr.IndexN(object,arguments,_)",
            "defpma_report_call_callee_indices(file:Ast::File&,expression:Ast::Expr",
            "pma_report(file,argument,current_module,index,annotations,table,bound,bound_types)")):
        raise SystemExit("parenthesized and explicit-generic private call targets must normalize without dropping index-argument checks")
    bare_call = facts['private_report'].index("Expr.Ident(callee_name,callee_line):")
    qualified_call = facts['private_report'].index("Expr.Scope(base,callee_name,callee_line):")
    qualified_body = facts['private_report'][qualified_call:]
    qualified_order = (
        "pma_report(file,base,current_module,index,annotations,table,bound,bound_types)",
        "owner:sview@source=pma_scope_owner(file,index,annotations,current_module,table,base,callee_name)",
        "pma_private_call_overloads_excluded(file,index,table,annotations,owner,callee_name,current_module,false,arguments,argument_names,bound,bound_types)",
        "table.diagnostics<-table.diagnostics.push(Diagnostic{kind:DiagnosticKind.PrivateMemberAccess,name:callee_name",
    )
    if bare_call > qualified_call or not all(fragment in facts['private_report'] for fragment in (
            "normalized_callee:Ast::Expr=pma_normalize_call_callee(file,callee,current_module,index,annotations,table,bound)",
            "matchnormalized_callee:",
            "pma_unqualified_call_owner(table,current_module,index,annotations,bound,callee_name)",
            "pma_private_call_overloads_excluded(file,index,table,annotations,owner,callee_name,current_module,true,arguments,argument_names,bound,bound_types)",
            "pma_report_call_callee_indices(file,callee,current_module,index,annotations,table,bound,bound_types)ifnormalized_callee_is_path")) or \
            not all(fragment in qualified_body for fragment in qualified_order) or \
            sorted(qualified_body.index(fragment) for fragment in qualified_order) != [qualified_body.index(fragment) for fragment in qualified_order] or \
            "notpma_within_module(current_module,owner)andnotprivate_candidates_excluded" not in qualified_body:
        raise SystemExit("call checking must normalize private call forms, preserve private base barriers, and check selected overload families")
    if "declaration_offsets:mutabledarray[u32]" not in facts['private_index_init'] or \
            "declaration_offsets:[]" not in facts['private_index_init']:
        raise SystemExit("private declaration offsets must be initialized alongside the member index")
    static_private_branch_match = re.search(r"(?ms)^module StaticPrivateBranchProvider:\n(.*?)(?=^(?:module |static if |using |from |def ))", call_shapes_text)
    static_private_branch_fixture = static_private_branch_match.group(1) if static_private_branch_match else ""
    if not all(fragment in compact(static_private_branch_fixture) for fragment in (
            "staticiffalse:private:defchoose()",
            "staticelse:public:defchoose()")):
        raise SystemExit("private-branch control must pair an inactive private declaration with an active public declaration of the same name")
    if not all(fragment in call_shapes_text for fragment in (
            "return (Provider::dispatch)(value)",
            "return Provider::dispatch[bool](value)",
            "return dispatch(value)",
            "return dispatch[bool](value)",
            "return Provider::sealed(value)",
            "return BroadProvider::prefer(value)",
            "return NamedProvider::inspect(value)",
            "return QualifiedNamedProvider::inspect(value)",
            "return LiteralProvider::choose(7)",
            "return wrap(fetch)",
            "return wrap(retrieve)",
            "static if false:",
            "static else:",
            "from InactivePrivateProvider import pick",
            "from ActivePublicProvider import pick",
            "def inactive_branch_private_import_does_not_shadow_public()",
            "return pick()",
            "module StaticPrivateBranchProvider:",
            "def inactive_branch_private_declaration_does_not_hide_public()",
            "return StaticPrivateBranchProvider::choose()",
            "def public_concrete_over_private_generic(value: i64)",
            "def public_named_concrete_over_private_generic(value: UniqueWidget)",
            "def same_spelling_different_modules_private_generic_winner(value: Widget)",
            "def public_concrete_literal_winner()",
            "def public_selective_function_value()")) or not all(fragment in call_shapes_smoke_text for fragment in (
            'private_call_overload_visibility_shapes.elisa',
            '[[ $(grep -cF \'is private to module\' <<< "$stage0_output") == 2 ]]',
            '[[ $(grep -cF \'is private to module\' <<< "$stage1_output") == 2 ]]',
            "QualifiedNamedProvider.inspect")):
        raise SystemExit("call-shape fixture must cover parenthesized, explicit-generic, static-import visibility, and private-only controls")

    if not all(fragment in unknown_static_import_text for fragment in (
            "const USE_PUBLIC_IMPORT: bool = true",
            "const USE_PRIVATE_WILDCARD: bool = false",
            "static if USE_PUBLIC_IMPORT:",
            "using PrivateWildcardProvider",
            "using PublicWildcardProvider",
            "from PublicProvider import pick",
            "static else:",
            "from PrivateProvider import pick",
            "def pick[T](value: T) -> i64:",
            "return pick(true)")) or not all(fragment in facts['unknown_static_import_smoke_text'] for fragment in (
            "private_call_static_unknown_import.elisa",
            "Stage0 rejected the definite root generic winner",
            "Stage1 reported an imported private overload that loses to the root generic")):
        raise SystemExit("named-constant static import fixture must preserve the direct root generic winner")

    static_true_import_control_text = STATIC_TRUE_IMPORT_CONTROL.read_text()
    static_true_import_control_smoke_text = STATIC_TRUE_IMPORT_CONTROL_SMOKE.read_text()
    if not all(fragment in static_true_import_control_text for fragment in (
            "static if true:",
            "const USE_PUBLIC_IMPORT: bool = true",
            "const USE_PUBLIC_IMPORT: bool = false",
            "const ENABLED: bool = true",
            "static if 'A' == 65:",
            "static if Flags::ENABLED:",
            "def pick(value: bool) -> i64:",
            "from PublicProvider import pick",
            "from PublicCharProvider import choose_char",
            "from PublicQualifiedProvider import choose_qualified",
            "static else:",
            "from PrivateProvider import pick",
            "from PrivateCharProvider import choose_char",
            "from PrivateQualifiedProvider import choose_qualified",
            "return pick(true) + choose_char(true) + choose_qualified(true)")) or not all(fragment in static_true_import_control_smoke_text for fragment in (
            "private_call_static_true_import_control.elisa",
            "Stage0 rejected the active public import",
            "Stage1 reported the inactive private import")):
        raise SystemExit("named-constant static-true control must prove that an inactive private import does not trigger PMA")

    inactive_static_statement_text = INACTIVE_STATIC_STATEMENT.read_text()
    inactive_static_statement_smoke_text = INACTIVE_STATIC_STATEMENT_SMOKE.read_text()
    if not all(fragment in inactive_static_statement_text for fragment in (
            "module PrivateProvider:",
            "private:",
            "def hidden() -> i64:",
            "def main() -> i64:",
            "static if false:",
            "PrivateProvider::hidden()")) or not all(fragment in inactive_static_statement_smoke_text for fragment in (
            "private_call_in_inactive_static_statement.elisa",
            "Stage0 reported a private call in an inactive static arm",
            "Stage1 reported a private call in an inactive static arm")):
        raise SystemExit("inactive static-statement control must bind Stage0 and Stage1 behavior for a private call in a known-false branch")

    nested_inactive_static_statement_text = NESTED_INACTIVE_STATIC_STATEMENT.read_text()
    nested_inactive_static_statement_smoke_text = NESTED_INACTIVE_STATIC_STATEMENT_SMOKE.read_text()
    if not all(fragment in nested_inactive_static_statement_text for fragment in (
            "static if false:",
            "static if true:",
            "PrivateProvider::hidden()")) or not all(fragment in nested_inactive_static_statement_smoke_text for fragment in (
            "private_call_in_nested_inactive_static_statement.elisa",
            "beneath an inactive enclosing arm")):
        raise SystemExit("nested static-statement control must bind an inner selected arm beneath a known-inactive parent")

    inactive_static_declaration_text = INACTIVE_STATIC_DECLARATION.read_text()
    inactive_static_declaration_smoke_text = INACTIVE_STATIC_DECLARATION_SMOKE.read_text()
    declaration_walk_source = function_section(consumer_text, "pma_walk_declarations")
    if not all(fragment in inactive_static_declaration_text for fragment in (
            "static if false:",
            "def inactive_function() -> i64:",
            "PrivateProvider::hidden()",
            "def main() -> i64:")) or not all(fragment in inactive_static_declaration_smoke_text for fragment in (
            "private_call_in_inactive_static_declaration.elisa",
            "inside an inactive function declaration")):
        raise SystemExit("inactive static-declaration control must bind skipped traversal through a known-false Decl.Scoped branch")
    if not all(fragment in declaration_walk_source for fragment in (
            "Decl.Scoped(scoped_body, scoped_line):",
            "pma_static_if_row_for_position(file, scoped_line)",
            "pma_static_if_row_selection(file, branch_row, current_module, table)",
            "continue if branch.known and not branch.selected",
            "pma_walk_declarations(scoped_body, file, current_module, index, annotations, table)")):
        raise SystemExit("PMA declaration traversal must skip a Decl.Scoped body when its static-if row is proven inactive")

    inactive_public_rank_text = INACTIVE_PUBLIC_OVERLOAD_RANK.read_text()
    inactive_public_rank_smoke_text = INACTIVE_PUBLIC_OVERLOAD_RANK_SMOKE.read_text()
    if not all(fragment in inactive_public_rank_text for fragment in (
            "module PrivateProvider:",
            "private:",
            "def choose(value: bool)",
            "static if false:",
            "def choose[T](value: T)",
            "from PrivateProvider import choose",
            "return choose(true)")) or not all(fragment in inactive_public_rank_smoke_text for fragment in (
            "private_call_inactive_public_overload_rank.elisa",
            "Stage0 missed the private imported call",
            "Stage1 let the inactive public generic suppress the privacy diagnostic")):
        raise SystemExit("inactive public overload control must bind the active private overload against a proven-inactive public generic")

    unproven_public_siblings_text = UNPROVEN_PUBLIC_SIBLINGS.read_text()
    unproven_public_siblings_smoke_text = UNPROVEN_PUBLIC_SIBLINGS_SMOKE.read_text()
    if not all(fragment in unproven_public_siblings_text for fragment in (
            "def choose_default[T](value: T, first: i64, second: i64)",
            "def choose_default(value: bool, optional: i64 = 0)",
            "choose_default(true, 1, 2)",
            "static if 1.0 == 0.0:",
            "static if \"a\" == \"b\":",
            "choose_float(true)",
            "choose_string(true)")) or not all(fragment in unproven_public_siblings_smoke_text for fragment in (
            "private_call_unproven_public_siblings.elisa",
            "only viable overload is private",
            "let an invalid-arity or unprovable public sibling suppress privacy")):
        raise SystemExit("unproven public sibling regression must cover defaulted arity and unsupported float/string conditions")

    same_line_import_pairing_text = SAME_LINE_IMPORT_PAIRING.read_text()
    same_line_import_pairing_smoke_text = SAME_LINE_IMPORT_PAIRING_SMOKE.read_text()
    if not all(fragment in same_line_import_pairing_text for fragment in (
            "module PrivateProvider:",
            "module PublicProvider:",
            "#line 70 public_import.elisa",
            "from PublicProvider import pick",
            "#line 70 private_import.elisa",
            "from PrivateProvider import pick",
            "return pick(true)")) or not all(fragment in same_line_import_pairing_smoke_text for fragment in (
            "private_call_same_line_import_pairing.elisa",
            "first public selective import",
            "another source at the same #line value")):
        raise SystemExit("selective-import regression must keep same-line source/member pairs distinct by token offset")

    module_alias_private_call_text = MODULE_ALIAS_PRIVATE_CALL.read_text()
    module_alias_private_call_smoke_text = MODULE_ALIAS_PRIVATE_CALL_SMOKE.read_text()
    if not all(fragment in module_alias_private_call_text for fragment in (
            "module Secret:",
            "private:",
            "def hidden() -> i64:",
            "using Secret as Pick",
            "return Pick::hidden()")) or not all(fragment in module_alias_private_call_smoke_text for fragment in (
            "private_call_module_alias.elisa",
            "private call through a module alias",
            "missed the private module-alias call")):
        raise SystemExit("module-alias private-call regression must bind alias-qualified access to its target private module")

    module_alias_precedence_text = MODULE_ALIAS_PRECEDENCE.read_text()
    module_alias_precedence_smoke_text = MODULE_ALIAS_PRECEDENCE_SMOKE.read_text()
    if not all(fragment in module_alias_precedence_text for fragment in (
            "static if true:",
            "using Secret as ActivePick",
            "static if false:",
            "using Secret as InactivePick",
            "using Public as InactivePick",
            "static if UNKNOWN_PICK:",
            "using Secret as UnknownPick",
            "using Public as UnknownPick",
            "ActivePick::hidden()",
            "InactivePick::hidden()",
            "UnknownPick::hidden()")) or not all(fragment in module_alias_precedence_smoke_text for fragment in (
            "private_call_module_alias_branch_precedence.elisa",
            "definitely-active private alias",
            "private_count")):
        raise SystemExit("module-alias regression must distinguish active, inactive, and unknown branches from unconditional aliases")

    module_alias_chain_text = MODULE_ALIAS_CHAIN.read_text()
    module_alias_chain_smoke_text = MODULE_ALIAS_CHAIN_SMOKE.read_text()
    if not all(fragment in module_alias_chain_text for fragment in (
            "using Secret as First",
            "using First as Second",
            "return Second::hidden()",
            "module Backend:",
            "module Nested:",
            "def nested_hidden() -> i64:",
            "using Backend as BackendRoot",
            "using BackendRoot::Nested as NestedSecret",
            "module ProjectionWinner:",
            "def winner_only() -> i64:",
            "module ProjectionLoser:",
            "def loser_only() -> i64:",
            "using ProjectionWinner as ProjectionChoice",
            "using ProjectionLoser as ProjectionChoice",
            "ProjectionChoice::winner_only()",
            "ProjectionChoice::loser_only()",
            "return Second::hidden() + NestedSecret::nested_hidden() + ProjectionChoice::winner_only() + ProjectionChoice::loser_only()")) or not all(fragment in module_alias_chain_smoke_text for fragment in (
            "private_call_module_alias_chain.elisa",
            "chained module alias",
            "private alias-chain call",
            "qualified private alias-suffix call",
            "nested_hidden",
            "ProjectionChoice.loser_only",
            'undefined identifier "NestedSecret.nested_hidden"',
            'undefined identifier "ProjectionChoice.winner_only"')):
        raise SystemExit("module-alias regression must resolve a private module through a chained alias")

    if not all(fragment in root_overloads_text for fragment in (
            "def choose(value: i64)",
            "def choose_selective(value: bool)",
            "from SelectiveProvider import choose_selective",
            "def prefer[T](value: T)",
            "def choose[T](value: T)",
            "def choose_selective[T](value: T)",
            "def prefer(value: bool)",
            "return choose(value)",
            "return choose_selective(value)",
            "return prefer(value)",
            "def local_rank[T](value: T)",
            "from Provider import local_rank",
            "def local_rank(value: bool)",
            "def local_concrete_wins(value: bool)",
            "return local_rank(value)")) or not all(fragment in root_overloads_smoke_text for fragment in (
            'private_call_root_overload_hidden_import.elisa',
            'grep -q \'^P 0$\' <<< "$stage1_output"',
            'is private to module')):
        raise SystemExit("root/local overload fixture must bind generic and concrete visible winners against private imported candidates")

    if 'include "../../src/semantic/private_module_boundary.elisa"' not in positive_text or \
            'include "./private_module_boundary.elisa"' not in negative_text:
        raise SystemExit("boundary proof fixtures must include the production helper")
