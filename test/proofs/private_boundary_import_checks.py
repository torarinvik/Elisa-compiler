"""Validate private-module import resolution."""
import re


def check_private_import_resolution(
    facts,
    compact,
    function_section,
    parser_const_text,
    parser_consume_using_target,
    parser_function_text,
    parser_text,
    parser_using_alias,
):
    if "pma_import_annotation_branch_selection_indexed(annotation,annotations,annotations,file,table)" not in facts['import_annotation_branch_wrapper']:
        raise SystemExit("non-indexed PMA callers must retain their complete annotation view")
    if not all(fragment in facts['selective_import_status'] for fragment in (
            'pma_import_row_branch_uncertain(annotations,"__from_member",member_annotation.name,member_annotation.module,member_annotation.line,member_annotation.offset)',
            'known_order<-false')) or not all(fragment in facts['wildcard_visibility'] for fragment in (
            'notrequire_definiteornotpma_import_row_branch_uncertain(annotations,annotation.owner,annotation.name,annotation.module,annotation.line,annotation.offset)')):
        raise SystemExit("uncertain selective or wildcard imports must not establish a definite public winner")
    if not all(fragment in facts['active_import_annotations'] for fragment in (
            'annotation.owner=="__from_member"',
            'annotation.name=="__binding_wildcard_import"',
            'annotation.name=="__using_alias"',
            'annotation.name=="__using_alias_target"')):
        raise SystemExit("PMA filtering must cover selective and wildcard import rows")
    if not all(fragment in parser_using_alias for fragment in (
            'name:"__using_alias",module:parser.current_module,line:alias_token.line,offset:alias_token.start',
            'name:"__using_alias_target",module:parser.current_module,line:alias_token.line,offset:alias_token.start',
            'parser.record_static_if_branch_rows("__using_alias_static_branch",alias_name,alias_token)')):
        raise SystemExit("alias branch markers must stay tied to the alias-token coordinates used by import cache selection")
    if not all(fragment in facts['build_import_views'] for fragment in (
            'pma_active_import_annotations(file,table)',
            'table.definite_import_annotations<-[]',
            'table.possible_import_annotations<-[]',
            'semantic_is_synthetic_unknown_import_marker(annotation)',
            'pma_import_row_branch_uncertain(active,annotation.owner,annotation.name,annotation.module,annotation.line,annotation.offset)',
            'table.possible_import_annotations.push(annotation)',
            'table.definite_import_annotations.push(annotation)')) or not all(fragment in facts['synthetic_import_marker'] for fragment in (
            'annotation.owner=="__pma_unknown_static_import"',
            'annotation.detail_name!=""')):
        raise SystemExit("post-collect import views must keep original unknown rows separate from definite caches")
    if 'semantic_is_synthetic_unknown_import_marker(annotation)' not in facts['wildcard_import_builder'] or 'semantic_is_synthetic_unknown_import_marker(annotation)' not in facts['binding_import_builder'] or 'semantic_is_synthetic_unknown_import_marker(target_row)' not in facts['alias_member_builder']:
        raise SystemExit("ordinary import cache builders must discard synthetic sentinels without dropping same-spelled source aliases")
    for setup in (facts['prepare_symbol_table'], facts['unresolved_table_setup'], facts['unresolved_references_setup']):
        if 'semantic_build_import_annotation_views(file,table)' not in setup or 'table.definite_import_annotations' not in setup:
            raise SystemExit("all table setup/rebuild entry points must build and consume the definite/possible import views")
    if not all(fragment in facts['prepare_symbol_table'] for fragment in (
            'table.protocol_annotations<-file.enum_annotations',
            'table.using_alias_rows.push(annotation)',
            'collect_range(file.top_decls,table,file.enum_annotations)',
            'semantic_build_import_annotation_views(file,table)')) or not (
            facts['prepare_symbol_table'].find('table.using_alias_rows.push(annotation)') < facts['prepare_symbol_table'].find('collect_range(file.top_decls,table,file.enum_annotations)') < facts['prepare_symbol_table'].find('semantic_build_import_annotation_views(file,table)')
        ):
        raise SystemExit("raw pre-collect using-alias ordering and post-collect import selection must remain separate")
    if not all(fragment in facts['possible_import_name_visible'] for fragment in (
            'semantic_possible_import_member_visible(table,name,current_scope)',
            'semantic_possible_import_module_alias(table,name,current_scope)',
            'module_import:bool=annotation.name=="__using"orannotation.name=="__using_alias_target"orannotation.name=="__binding_wildcard_import"',
            'module_importandsemantic_import_scope_visible(annotation.module,current_scope)',
            'semantic_possible_import_import_row_member_visible(table,annotation,name,current_scope)')) or not all(fragment in facts['possible_import_member_visible'] for fragment in (
            'annotation.owner=="__from_member"',
            'annotation.name==name',
            'semantic_import_scope_visible(annotation.module,current_scope)')) or not all(fragment in facts['possible_import_type_selection'] for fragment in (
            'semantic_import_scope_visible(annotation.module,current_scope)',
            'source.owner!="__from_src"',
            'semantic_possible_import_type_path_candidate_matches(table,symbol.module_owner,source.name,name,kind,include_constants,source.module,source.offset)',
            'annotation.name=="__using_alias_target"',
            'semantic_possible_import_alias_target_row_can_win(annotation,current_scope,table)',
            'annotation.name=="__using"',
            'semantic_import_using_row_has_alias_pair(annotation,table)',
            'annotation.name=="__binding_wildcard_import"',
            'semantic_possible_import_type_path_candidate_matches(table,symbol.module_owner,annotation.owner,name,kind,include_constants,annotation.module,annotation.offset)')) or not all(fragment in facts['possible_import_alias'] for fragment in (
            'annotation.name=="__using_alias"',
            'annotation.owner==alias_name',
            'semantic_possible_import_alias_can_win(annotation,current_scope,4294967295,table)')) or not all(fragment in facts['possible_import_module_visible'] for fragment in (
            'annotation.name=="__using_alias_target"',
            'semantic_possible_import_alias_target_row_can_win(annotation,current_scope,table)',
            'semantic_import_using_row_has_alias_pair(annotation,table)',
            'semantic_possible_import_module_path_module_candidate_matches(table,owner,annotation.owner,annotation.module,annotation.offset)')) or not all(fragment in facts['possible_import_member_owner'] for fragment in (
            'semantic_possible_import_module_path_candidate_matches(table,owner,source.name,name,source.module,source.offset)')) or not all(fragment in facts['possible_import_module_member'] for fragment in (
            'semantic_possible_import_module_path_member_visible(table,owner,name,current_scope,4294967295)',
            'semantic_possible_import_alias_target_row_can_win(target,current_scope,table)',
            'semantic_possible_import_module_path_member_visible(table,target.owner,name,target.module,target.offset)')) or not all(fragment in facts['possible_import_module_path'] for fragment in (
            'candidate_owner==target',
            'at_scope_boundary:bool=prefix_length==import_scope.lenor(prefix_length+1.usize()<import_scope.lenandimport_scope[prefix_length]==58andimport_scope[prefix_length+1.usize()]==58)',
            'expected_length:usize=prefix_length+2.usize()+target.len',
            'candidate_owner.len==expected_length',
            'candidate_owner[prefix_length]==58andcandidate_owner[prefix_length+1.usize()]==58',
            'matches_target<-falseifcandidate_owner[prefix_length+2.usize()+index]!=target[index]',
            'returntrueifmatches_target')):
        raise SystemExit("possible imports must preserve ordinary scope visibility and resolve candidate paths through the selected alias or raw root")
    if not all(fragment in facts['possible_import_alias_target_row_can_win'] for fragment in (
            'target_row.name!="__using_alias_target"',
            'candidate.name=="__using_alias"',
            'candidate.name=="__using_alias_target"',
            'candidate.module==target_row.module',
            'candidate.line==target_row.line',
            'candidate.offset==target_row.offset',
            'alias_count!=1.usize()',
            'target_count!=1.usize()',
            'alias.owner==""',
            'paired_target_owner==""',
            'paired_target_owner!=target_row.owner',
            'semantic_possible_import_alias_can_win(alias,current_scope,4294967295,table)')) or not all(fragment in facts['possible_import_alias_target_prefix'] for fragment in (
            'return(false,false,0)ifnotalias.known',
            'ifalias.found:',
            'semantic_import_module_path_prefix_matches(candidate_owner,alias.target,alias.scope)',
            'semantic_possible_import_alias_target_prefix(candidate_owner,alias.raw_target,alias.scope,alias.offset,table,depth+1.u32())',
            'return(true,false,0)ifnotcanonical_prefix.matches',
            'semantic_import_module_path_prefix_matches(candidate_owner,target_path,import_scope)')) or not all(fragment in facts['possible_import_alias_target_matches'] for fragment in (
            'semantic_possible_import_alias_target_prefix(candidate_owner,target_path,import_scope,before_offset,table)',
            'returntrueifnottarget_prefix.known',
            'returnfalseifnottarget_prefix.matches',
            'appended.end==candidate_owner.len')) or not all(fragment in facts['possible_import_alias_target_head_status'] for fragment in (
            'semantic_possible_import_alias_head_target(alias_name,import_scope,before_offset,table)',
            'return(alias.known,alias.found)')) or not all(fragment in facts['possible_import_alias_target_alias_matches'] for fragment in (
            'semantic_possible_import_alias_target_head_status(target_path,import_scope,before_offset,table)',
            'returntrueifnothead.known',
            'returnfalseifnothead.found',
            'semantic_possible_import_alias_target_matches(candidate_owner,target_path,"",import_scope,before_offset,table)')) or not all(fragment in facts['possible_import_module_path_alias_member'] for fragment in (
            'semantic_possible_import_alias_target_alias_matches(symbol.module_owner,target_path,import_scope,before_offset,table)',
            'semantic_possible_import_alias_target_alias_matches(table.module_member_owner[member_index],target_path,import_scope,before_offset,table)')) or not all(fragment in facts['possible_import_module_path_member'] for fragment in (
            'semantic_possible_import_alias_target_head_status(target_path,import_scope,before_offset,table)',
            'semantic_possible_import_module_path_alias_member_visible(table,target_path,name,import_scope,before_offset)',
            'semantic_import_module_path_matches(symbol.module_owner,target_path,import_scope)',
            'semantic_import_module_path_matches(table.module_member_owner[member_index],target_path,import_scope)')) or not all(fragment in facts['possible_import_module_path_candidate'] for fragment in (
            'semantic_possible_import_alias_target_head_status(target_path,import_scope,before_offset,table)',
            'semantic_possible_import_module_path_alias_member_visible(table,target_path,name,import_scope,before_offset)',
            'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
            'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)')) or not all(fragment in facts['possible_import_type_path_candidate'] for fragment in (
            'semantic_possible_import_alias_target_head_status(target_path,import_scope,before_offset,table)',
            'symbol.name==name',
            'symbol.kind==kind',
            'semantic_possible_import_alias_target_alias_matches(symbol.module_owner,target_path,import_scope,before_offset,table)',
            'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
            'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)')) or not all(fragment in facts['possible_import_module_symbol_alias'] for fragment in (
            'alias.name=="__using_alias"',
            'alias.owner==symbol.name',
            'alias.line==symbol.line',
            'alias.offset==symbol.offset')) or not all(fragment in facts['possible_import_module_path_alias_module'] for fragment in (
            'formodule_rowintable.module_symbol_rows',
            'semantic_possible_import_module_symbol_is_using_alias(symbol,table)',
            'semantic_possible_import_alias_target_alias_matches(symbol.name,target_path,import_scope,before_offset,table)')) or not all(fragment in facts['possible_import_module_path_module_candidate'] for fragment in (
            'semantic_possible_import_alias_target_head_status(target_path,import_scope,before_offset,table)',
            'semantic_possible_import_module_path_alias_module_visible(table,target_path,import_scope,before_offset)',
            'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
            'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)')) or not all(fragment in facts['possible_import_import_row_member'] for fragment in (
            'import_row.name=="__using_alias_target"',
            'semantic_possible_import_alias_target_row_can_win(import_row,current_scope,table)',
            'import_row.name=="__using"',
            'semantic_import_using_row_has_alias_pair(import_row,table)',
            'semantic_possible_import_module_path_member_visible(table,import_row.owner,name,import_row.module,import_row.offset)')):
        raise SystemExit("possible alias targets and selective imports must preserve exact winner gating and candidate-level alias-before-raw selection")
    if not (facts['possible_import_alias_target_prefix'].find('ifalias.found:') < facts['possible_import_alias_target_prefix'].find('direct:(matches:bool,end:usize)=semantic_import_module_path_prefix_matches(candidate_owner,target_path,import_scope)')):
        raise SystemExit("nested raw-target expansion must only fall back after the alias head is known absent")
    for source, order in (
            (facts['possible_import_module_path_member'], (
                'returntrueifnotalias_head.known',
                'ifalias_head.found:',
                'semantic_possible_import_module_path_alias_member_visible(table,target_path,name,import_scope,before_offset)',
                'semantic_import_module_path_matches(symbol.module_owner,target_path,import_scope)')),
            (facts['possible_import_module_path_candidate'], (
                'semantic_possible_import_module_path_alias_member_visible(table,target_path,name,import_scope,before_offset)',
                'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
                'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)')),
            (facts['possible_import_type_path_candidate'], (
                'alias_candidate_exists:bool=anysymbolintable.symbols',
                'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
                'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)')),
            (facts['possible_import_module_path_module_candidate'], (
                'semantic_possible_import_module_path_alias_module_visible(table,target_path,import_scope,before_offset)',
                'semantic_possible_import_alias_target_alias_matches(candidate_owner,target_path,import_scope,before_offset,table)',
                'semantic_import_module_path_matches(candidate_owner,target_path,import_scope)'))):
        positions = [source.find(fragment) for fragment in order]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            raise SystemExit("possible-import candidate selection must choose the complete alias candidate set before raw fallback")
    if any(fragment in function for function in (facts['possible_import_module_visible'], facts['possible_import_type_selection'], facts['possible_import_member_owner'], facts['possible_import_module_member']) for fragment in (
            'semantic_import_module_path_matches(owner,annotation.owner,annotation.module)',
            'semantic_import_module_path_matches(symbol.module_owner,annotation.owner,annotation.module)',
            'semantic_import_module_path_matches(owner,source.name,source.module)',
            'semantic_import_module_path_matches(symbol.module_owner,source.name,source.module)',
            'semantic_possible_import_alias_module_path_matches(owner,annotation.owner,annotation.module,annotation.offset,table)',
            'semantic_possible_import_alias_module_path_matches(symbol.module_owner,annotation.owner,annotation.module,annotation.offset,table)',
            'semantic_possible_import_alias_module_path_matches(owner,source.name,source.module,source.offset,table)',
            'semantic_possible_import_alias_module_path_matches(symbol.module_owner,source.name,source.module,source.offset,table)')):
        raise SystemExit("possible-import consumers must not OR alias targets with raw root-path matches")
    if not all(fragment in facts['possible_import_module_path_suffix'] for fragment in (
            'tail_length:usize=target.len+2.usize()+suffix.len',
            'candidate_owner.len==tail_length',
            'candidate_owner[target_end]==58',
            'candidate_owner[target_end+1.usize()]==58')) or not all(fragment in facts['possible_import_alias_module_path'] for fragment in (
            'string_view_slice(target,0,head_length.i64())',
            'string_view_slice(target,(head_length+2.usize()).i64(),target.len.i64())',
            'semantic_possible_import_alias_can_win(alias,import_scope,before_offset,table)',
            'semantic_possible_import_alias_target_matches(candidate_owner,target_row.owner,suffix,target_row.module,target_row.offset,table)',
            'semantic_possible_import_alias_dependency_exists(raw_target_row.owner,alias.module,alias.offset,table)',
            'semantic_possible_import_alias_target_matches(candidate_owner,raw_target_row.owner,suffix,raw_target_row.module,raw_target_row.offset,table)')):
        raise SystemExit("possible import path matching must preserve qualified alias suffixes and use the selected global alias rows")
    if not all(fragment in facts['possible_import_alias_dependency'] for fragment in (
            'depth>=64',
            'semantic_possible_import_alias_head_target(alias_name,import_scope,before_offset,table)',
            'semantic_possible_import_alias_dependency_exists(alias.raw_target,alias.scope,alias.offset,table,depth+1.u32())')) or not all(fragment in facts['possible_import_alias_branch'] for fragment in (
            'marker.name=="__using_alias_static_branch"',
            'marker.detail_name==alias.owner')) or not all(fragment in facts['possible_import_alias_branch_marker_at'] for fragment in (
            'marker.identity_id==4294967295',
            'seen==ordinal',
            'return(true,marker.identity_id)')) or not all(fragment in facts['possible_import_alias_branch_marker_count'] for fragment in (
            'marker.identity_id==4294967295',
            'return(true,count)')) or not all(fragment in facts['possible_import_alias_branch_stack'] for fragment in (
            'shared_count:usize=left_stack.countifleft_stack.count<right_stack.countelseright_stack.count',
            'left_marker.identity!=right_marker.identity',
            'shared_prefixandleft_stack.count==right_stack.count')):
        raise SystemExit("possible alias dependencies must use exact source targets and preserve branch identity stacks")
    if not all(fragment in facts['possible_import_alias_order'] for fragment in (
            'left.module==right.module',
            'branch_relation<-semantic_possible_import_alias_branch_stack_relation(left,right,table)',
            'left_is_branchandright_is_branchandnotbranch_relation.known',
            'return(true,notleft_is_branch)ifleft_is_branch!=right_is_branch',
            'branch_relation.shared_prefix',
            'branch_relation.left_count<branch_relation.right_count',
            'both_definite:bool=left_is_branchandright_is_branchandsemantic_possible_import_alias_is_definite(left,table)andsemantic_possible_import_alias_is_definite(right,table)',
            'return(true,true)ifbranch_relation.left_count<=branch_relation.right_count',
            'return(true,false)ifbranch_relation.right_count<=branch_relation.left_count',
            'ifnotright_is_branch:return(false,false)ifleft.offset==right.offsetreturn(true,left.offset<right.offset)',
            'ifnotleft_is_branch:return(false,false)ifleft.offset==right.offsetreturn(true,left.offset<right.offset)',
            'return(true,left.offset<right.offset)',
            'named_type_owner_is_lexical(left.module,right.module)',
            'named_type_owner_is_lexical(right.module,left.module)',
            'left.offset<right.offset')) or not all(fragment in facts['possible_import_alias_definite'] for fragment in (
            'row.name==alias.name',
            'row.owner==alias.owner',
            'row.module==alias.module',
            'row.line==alias.line',
            'row.offset==alias.offset')) or not all(fragment in facts['possible_import_alias_position'] for fragment in (
            'semantic_possible_import_alias_precedes(alias,requester,table)',
            'requester.name=="__using_alias"',
            'alias.module==scope',
            'named_type_owner_is_lexical(alias.module,scope)',
            'alias_is_branch',
            'return(true,true)')):
        raise SystemExit("possible alias winner selection must use Core's global order and fail closed for unknown branch relations")
    if not all(fragment in facts['possible_import_alias_head_target'] for fragment in (
            'table.definite_import_annotations',
            'semantic_possible_import_alias_precedes_position(alias,import_scope,before_offset,table)',
            'semantic_possible_import_alias_precedes(other,alias,table)',
            'raw_target_count!=1.usize()',
            'canonical_target_count!=1.usize()',
            'table.possible_import_annotations')):
        raise SystemExit("possible alias chains must choose one prior global winner and pair it with one raw/canonical target")
    if not all(fragment in facts['possible_import_alias_head_target'] for fragment in (
            'candidate_wins:mutablebool=true',
            'ifselected_found:',
            'raw_target_count:mutableusize=0',
            'canonical_target_count:mutableusize=0')) or (
            facts['possible_import_alias_head_target'].index('raw_target_count:mutableusize=0') <
            facts['possible_import_alias_head_target'].index('candidate_wins:mutablebool=true')):
        raise SystemExit("possible alias target rows must be validated after the final global winner is selected")
    if not all(fragment in facts['possible_import_alias_precedence'] for fragment in (
            'semantic_possible_import_alias_precedes_position(alias,import_scope,before_offset,table)',
            'table.definite_import_annotations',
            'semantic_possible_import_alias_precedes(candidate,selected,table)',
            'semantic_possible_import_alias_precedes(alias,selected,table)',
            'other_before_position.knownandnotother_before_position.precedes',
            'returntrueiffound_priorand(notselected_foundorwinner_ambiguous)',
            'returnfalseifcandidate_before.knownandnotcandidate_before.precedes',
            'returnnotcandidate_before.knownorcandidate_before.precedes',
            'returntrueifnotorder.known')) or 'semantic_possible_import_alias_can_win(alias,import_scope,before_offset,table)' not in facts['possible_import_alias_module_path']:
        raise SystemExit("possible alias paths must account for global definite winners and remain conservative when ordering is unknown")
    if not all(fragment in facts['resolver_name_known'] for fragment in ('semantic_possible_import_name_visible(table,name,table.current_module)',)) or not all(fragment in facts['resolver_name_classification'] for fragment in (
            'semantic_possible_import_name_visible(table,name,table.current_module)')) or not all(fragment in facts['resolver_wildcard_uncertainty'] for fragment in (
            'table.possible_import_annotations',
            'rew_has_type_declaration(name,possible.owner,table)')) or not all(fragment in facts['resolver_module_alias'] for fragment in (
            'semantic_possible_import_module_alias(table,name,table.current_module)')) or not all(fragment in facts['resolver_qualified_alias_uncertainty'] for fragment in (
            'semantic_possible_import_module_member_visible(table,base_name,name,table.current_module)')):
        raise SystemExit("resolver name and wildcard ambiguity paths must account conservatively for possible imports")
    if not all(fragment in facts['binding_nominal_lookup'] for fragment in (
            'semantic_possible_import_may_select_type(table,name,SymbolKind.Struct,scope,include_constants)',
            'possible_import_match')) or not all(fragment in facts['named_struct_lookup'] for fragment in (
            'semantic_possible_import_may_select_type(table,type_name,SymbolKind.Struct,table.current_module)',
            'possible_import_matchandbest_rank==0')) or not all(fragment in facts['enum_owner_lookup'] for fragment in (
            'semantic_possible_import_may_select_type(table,name,kind,context_module)')):
        raise SystemExit("exact nominal and enum-owner selection must decline when a possible import can change the winner")
    if not all(fragment in facts['construct_call_lookup'] for fragment in ('semantic_possible_import_name_visible(table,name,table.current_module)',)) or not all(fragment in facts['readonly_callee_lookup'] for fragment in (
            'semantic_possible_import_name_visible(table,callee,caller_owner)')) or not all(fragment in facts['private_field_owner_lookup'] for fragment in (
            'semantic_possible_import_module_visible(table,owner,scope)',
            'semantic_possible_import_member_owner_visible(table,owner,name,scope)')):
        raise SystemExit("type, constructor, readonly, and private-field consumers must not choose a definite owner from possible imports")
    if 'UNKNOWN_DUPLICATE_IMPORT' not in facts['module_alias_precedence_text'] or 'using Secret, Secret as UnknownDuplicateAlias' not in facts['module_alias_precedence_text'] or 'UnknownDuplicateAlias::hidden()' not in facts['module_alias_precedence_text']:
        raise SystemExit("aliased using branch regression must cover a wildcard row followed by a same-target alias on one source line")
    if not all(fragment in compact(parser_text) for fragment in (
            'parser<-parser.record_static_if_branch_rows("__from_member_static_branch",member,token)',
            'parser<-parser.record_static_if_branch_markers(marker_name,detail_name,token.line,token.start)',
            'owner:"__static_if_branch",name:marker_name,detail_name:detail_name,module:marker_module',
            'identity_id:branch_identity')):
        raise SystemExit("selective import parser rows must carry the member token's enclosing static-if branch identities")
    function_declaration_parser = compact(function_section(parser_function_text, "function_declaration"))
    if 'parser<-parser.record_static_if_branch_rows("__function_static_branch",function_name,token)' not in function_declaration_parser:
        raise SystemExit("function declarations must carry their exact enclosing static-if branch identities for overload ranking")
    const_declaration_parser = compact(function_section(parser_const_text, "const_declaration"))
    if 'parser.record_static_if_branch_rows("__const_static_branch",Lexer::text_or_empty(name_token,parser.source,parser.source_length),token)ifnotis_global' not in const_declaration_parser:
        raise SystemExit("immutable const declarations must carry static-if branch identities for PMA condition folding")
    private_markers = compact(function_section(parser_text, "record_static_if_branch_markers"))
    if not all(fragment in facts['private_record'] for fragment in (
            'parser<-parser.record_static_if_branch_markers("__private_member_static_branch",member_name,section_line,member_position.offset)',)) or not all(fragment in private_markers for fragment in (
            'marker_name',
            'detail_name',
            'marker_module',
            'marker_line',
            'marker_offset',
            'owner:"__static_if_branch"',
            'identity_id:branch_identity')):
        raise SystemExit("private declarations must carry their enclosing static-if branch identities")
    if not all(fragment in facts['import_annotation_branch_selection'] for fragment in (
            'annotation.owner=="__private_member"',
            'module_annotation.owner!="__private_member_module"',
            'pma_import_branch_selection(markers,file,table,"__static_if_branch","__private_member_static_branch",annotation.name,member_module,annotation.line,annotation.offset)',
            'annotation.name=="__using"',
            '"__binding_wildcard_import_static_branch"',
            'annotation.name=="__using_alias"',
            '"__using_alias_static_branch"',
            'annotation.name=="__using_alias_target"',
            '"__private_member_static_branch"',
            'module_annotation.name')) or not all(fragment in facts['active_import_annotations'] for fragment in (
            'private_member_row:bool=annotation.owner=="__private_member"',
            'branch_row:bool=import_roworprivate_member_row',
            'annotation.name=="__using"',
            'annotation.name=="__using_alias"',
            'annotation.name=="__using_alias_target"',
            'branch.knownandnotbranch.active')):
        raise SystemExit("PMA must remove proven-inactive private declarations before building its privacy index")
    if not all(fragment in parser_consume_using_target for fragment in (
            'parser.record_using_annotation(Ast::EnumAnnotation{owner:recorded_target,name:"__using",module:parser.current_module,line:target_token.line,offset:target_token.start})',
            'parser.using_alias(alias_target)')) or not all(fragment in parser_using_alias for fragment in (
            'offset:alias_token.start',
            'name:"__using_alias_target"')):
        raise SystemExit("the legacy using row and alias pair must retain their distinct parser token offsets")
    if not all(fragment in facts['import_using_row_alias_pair'] for fragment in (
            'using_row.name!="__using"',
            'candidate.module!=using_row.module',
            'candidate.line!=using_row.line',
            'candidate.offset<=using_row.offset',
            'candidate.offset<next_using_offset',
            'forcandidateintable.possible_import_annotations',
            'target_row.owner!=using_row.owner',
            'target_row.module!=using_row.module',
            'target_row.line!=using_row.line',
            'target_row.offset<=using_row.offset',
            'target_row.offset>=next_using_offset',
            'alias_row.name=="__using_alias"',
            'alias_row.module==target_row.module',
            'alias_row.line==target_row.line',
            'alias_row.offset==target_row.offset',
            'foralias_rowintable.possible_import_annotations',
            'fortarget_rowintable.possible_import_annotations')):
        raise SystemExit("alias-associated legacy using rows must be identified without altering the raw import views")
    if not all(fragment in facts['binding_import_builder'] for fragment in (
            'annotation.name=="__using_alias_target"',
            'binding_resolve_module_alias_target(annotation.owner,requester,table)',
            'normalized<-annotation{owner=canonical_target}',
            'table.binding_import_annotations.push(normalized)')) or not all(fragment in facts['import_alias_pair_target'] for fragment in (
            'candidate.name=="__using_alias"',
            'target.name=="__using_alias_target"',
            'candidate.module==alias.module',
            'candidate.line==alias.line',
            'candidate.offset==alias.offset',
            'target.module==alias.module',
            'target.line==alias.line',
            'target.offset==alias.offset',
            'alias_count!=1.usize()',
            'definite_alias_count!=1.usize()',
            'target_count!=1.usize()',
            'definite_target_count!=1.usize()',
            'target_owner==""')) or not all(fragment in facts['import_alias_global_winner'] for fragment in (
            'semantic_possible_import_alias_is_definite(alias,table)',
            'semantic_import_alias_pair_target(alias,table)',
            'semantic_possible_import_alias_precedes(candidate,alias,table)',
            'returnfalseifnotorder.knownororder.precedes')) or not all(fragment in facts['import_alias_target_global_winner'] for fragment in (
            'target.name!="__using_alias_target"',
            'pair.target!=target.owner',
            'semantic_import_alias_is_global_winner(alias,table)')) or not all(fragment in facts['import_alias_target_canonical_owner'] for fragment in (
            'semantic_import_alias_target_is_global_winner(target,table)',
            'binding_target.name=="__using_alias_target"',
            'binding_target.module==target.module',
            'binding_target.line==target.line',
            'binding_target.offset==target.offset',
            'canonical_count!=1.usize()',
            'canonical_owner==""')):
        raise SystemExit("module-alias projections must require one exact winner pair and one canonical target")
