"""epc4 (the Energy Actions card bundle rebuilt from the plan-core sources after the Gentle Smart Charging work: the model review fixes G1 to G7 and the model
constraints from the offline limits and authority resolution; offline, nothing installed, nothing actuated). ONE FROZEN edit (PEX): the card's rebuilt
dist/ecco-energy-actions-card.js and nothing else about it. ADDED: this module only. ZERO other frozen or chain-pinned edit, ZERO firmware, Home Assistant
package, deployment, registry data, Intelligence, ecco_core or VERSION.yaml byte, ZERO Modbus operation, no service call and no write of any kind.

POSITION. This entry comes AFTER ecf1 (the card corrections, whose bundle is the first state below: sha256 2270a0be...), so its pairs run from ecf1's bundle to the
bundle the combined sources build. It is the stacked form of the earlier epc4 (which ran from epc2's bundle, when no card correction existed): epc3, then ecf1,
then epc4. Its fingerprint is hash-linked to ecf1's, not to epc3's.

WHY. The card imports the plan-core package through its index, which re-exports the Gentle controller model (epc3). The bundler keeps the model's top-level
initialisers (the frozen constants, the provenance table and the one call that builds it) although the card never calls the model, so a change to those
constants changes the bundle. The Gentle work changed them: the one authoritative max-charge-power basis table, the four actuator profiles (UNCONSTRAINED,
FREE_POWER_LEASE, TOU_SLOT_EDITOR, RATE_CONTROLLER_PROPOSED), eight more default parameters (26 in all, from 18), one more recommended parameter, a changed default
policy (unknown demand defaults to FALLBACK; the setpoint basis and the actuator profile are explicit) and ten more provenance rows (33 in all, from 23), and
the minifier then renames symbols in 129 of the bundle's 2073 lines. A build of the sources is therefore no longer byte-identical to the bundle ecf1 declares,
and the bundle must be declared again, by a NEW entry: no older entry, checkpoint or fingerprint is touched (ecf1 stays exactly as it is).

WHAT THE HUNKS ARE (measured, not assumed). (1) The same two source trees (ecf1's tip and the combined tree) were built with the identifier minifier
switched off: the whole difference is 17 regions, all inside the controller model's top-level constants and provenance table, and no function, no reference and
no call of the card moved. (2) The stronger check: in the combined tree, put the one file `frontend/ecco-plan-core/src/gentleController.ts` back to its text at
ecf1's tip and build with the committed tool (`node build.mjs`, esbuild 0.28.1): the result is byte-identical to the bundle ecf1 declares (sha256 2270a0be...),
although the tree still holds the new `gentleAdvice.ts`, `gentleNight.ts` and the edited `time.ts` (the card never imports them and the package index does not
re-export the first two, so they add not one byte). The whole difference therefore comes from that one model file. Of the 987 hunks below, 12 are the model's
constants (their changed text is not a rename) and 975 are the minifier's renames of short names that those constants shift (a hunk is a changed region widened
with context until its text occurs exactly once). The model's bindings are read only by the provenance builder, which runs once at load and whose result
nothing reads; the card's source imports none of them.

NOT DECLARED. The plan-core files the Gentle work adds or edits (README.md, the sources, tests and tools) are epc1 / epc3 added files or lie outside every frozen
or chain-pinned set, and so are the Python tools and tests it adds, so their content is not declared (the rule epc3's module records for Gentle v2), and no file
is added besides this module. The card folder gains no file: its tracked files stay exactly as ecf1 declares them.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact (before, after) pair
generated from the real diff and round-trip-checked (apply then revert reproduces both texts byte for byte), and the reverter raises unless each of its edits is
present exactly once. The post-export chain entry `epc4` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES; registry/tests/_pex.py) carries them; its
fingerprint is sealed with _pex.sealed, hash-linked to ecf1's, and must be sealed again if another entry merges before it.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

ID = 'epc4'

ADDED_FILES = frozenset({
    'registry/tests/_epc4_scope.py',
})

import hashlib


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"{ID} scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"{ID} scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"{ID} scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) the rebuilt bundle ------------------------------------------------------------------------
DIST_REL = 'frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js'
# 25 Nov 2026 (owner: the card corrections go to production first, the Gentle work is stacked on them): the pairs run from the bundle ecf1 declares to the bundle
# the combined sources build (esbuild 0.28.1, `node build.mjs`); the new bundle checkpoint is stated in _scope_chain.py. "model" marks the hunks inside the
# controller model's constants; every other pair is a rename.
DIST_EDITS = (
    # 001 rename
    ('var Cr=Obje',
     'var Dr=Obje'),
    # 002 rename
    ('r;var O=(e,n,',
     'r;var I=(e,n,'),
    # 003 rename
    (',t):n,o=e.length-1,i;o>=0;o--)(i=e[o])&&(a=(r?i(n,t,a):i(a))||',
     ',t):n,i=e.length-1,o;i>=0;i--)(o=e[i])&&(a=(r?o(n,t,a):o(a))||'),
    # 004 rename
    ('r&&a&&Cr(n,t,',
     'r&&a&&Dr(n,t,'),
    # 005 rename
    ('akMap,Re=clas',
     'akMap,Pe=clas'),
    # 006 rename
    ('=>new Re(type',
     '=>new Pe(type'),
    # 007 rename
    ('((r,a,o)=>r+(i=>{if(i._$css',
     '((r,a,i)=>r+(o=>{if(o._$css'),
    # 008 rename
    ('eturn i.cssTe',
     'eturn o.cssTe'),
    # 009 rename
    ('ypeof i=="num',
     'ypeof o=="num'),
    # 010 rename
    ('eturn i;throw',
     'eturn o;throw'),
    # 011 rename
    ('lt: "+i+". Us',
     'lt: "+o+". Us'),
    # 012 rename
    ('(a)+e[o+1],e[',
     '(a)+e[i+1],e['),
    # 013 rename
    ('n new Re(t,e,',
     'n new Pe(t,e,'),
    # 014 rename
    ('ar{is:Ir,defi',
     'ar{is:Or,defi'),
    # 015 rename
    ('perty:Or,getO',
     'perty:Ir,getO'),
    # 016 rename
    ('Types,Vr=nn?n',
     'Types,Ur=nn?n'),
    # 017 rename
    ('pt:"",Ur=Ye.r',
     'pt:"",Vr=Ye.r'),
    # 018 rename
    ('pport,Pe=(e,n',
     'pport,Re=(e,n'),
    # 019 rename
    ('n:e=e?Vr:null',
     'n:e=e?Ur:null'),
    # 020 rename
    (',n)=>!Ir(e,n)',
     ',n)=>!Or(e,n)'),
    # 021 rename
    ('id 0&&Or(this',
     'id 0&&Ir(this'),
    # 022 rename
    ('a,set:o}=$r(t',
     'a,set:i}=$r(t'),
    # 023 rename
    ('},set(i){this[t]=i}};ret',
     '},set(o){this[t]=o}};ret'),
    # 024 rename
    ('a,set(i){let ',
     'a,set(o){let '),
    # 025 rename
    ('this);o?.call(this,i),this',
     'this);i?.call(this,o),this'),
    # 026 rename
    ('perty(Pe("ele',
     'perty(Re("ele'),
    # 027 rename
    ('perty(Pe("fin',
     'perty(Re("fin'),
    # 028 rename
    ('perty(Pe("pro',
     'perty(Re("pro'),
    # 029 rename
    ('){let o=(r.co',
     '){let i=(r.co'),
    # 030 rename
    ('$Em=n,o==null',
     '$Em=n,i==null'),
    # 031 rename
    ('ute(a,o),this',
     'ute(a,i),this'),
    # 032 rename
    ('){let o=r.get',
     '){let i=r.get'),
    # 033 rename
    ('ns(a),i=typeof o.conve',
     'ns(a),o=typeof i.conve'),
    # 034 rename
    ('ibute:o.converter}:o.conve',
     'ibute:i.converter}:i.conve'),
    # 035 rename
    ('oid 0?o.conve',
     'oid 0?i.conve'),
    # 036 rename
    ('let s=i.fromA',
     'let s=o.fromA'),
    # 037 rename
    ('ute(t,o.type)',
     'ute(t,i.type)'),
    # 038 rename
    (',a=!1,o){if(n',
     ',a=!1,i){if(n'),
    # 039 rename
    ('void 0){let i=this.constr',
     'void 0){let o=this.constr'),
    # 040 rename
    ('=!1&&(o=this[',
     '=!1&&(i=this['),
    # 041 rename
    ('),r??=i.getPr',
     '),r??=o.getPr'),
    # 042 rename
    ('??qe)(o,t)||r',
     '??qe)(i,t)||r'),
    # 043 rename
    ('lect&&o===thi',
     'lect&&i===thi'),
    # 044 rename
    ('ibute(i._$Eu(',
     'ibute(o._$Eu('),
    # 045 rename
    ('apped:o},i){r&&!',
     'apped:i},o){r&&!'),
    # 046 rename
    ('set(n,i??t??t',
     'set(n,o??t??t'),
    # 047 rename
    ('s[n]),o!==!0||i!==voi',
     's[n]),i!==!0||o!==voi'),
    # 048 rename
    ('let[a,o]of th',
     'let[a,i]of th'),
    # 049 rename
    ('is[a]=o;this.',
     'is[a]=i;this.'),
    # 050 rename
    ('let[a,o]of r)',
     'let[a,i]of r)'),
    # 051 rename
    ('apped:i}=o,s=this[a];i!==!0|',
     'apped:o}=i,s=this[a];o!==!0|'),
    # 052 rename
    ('oid 0,o,s)}}l',
     'oid 0,i,s)}}l'),
    # 053 rename
    ('"},te[Pe("ele',
     '"},te[Re("ele'),
    # 054 rename
    ('ap,te[Pe("fin',
     'ap,te[Re("fin'),
    # 055 rename
    ('w Map,Ur?.({R',
     'w Map,Vr?.({R'),
    # 056 rename
    ('lit$",ie=`lit',
     'lit$",oe=`lit'),
    # 057 rename
    ('2)}$`,hn="?"+ie,Hr=`<${hn}>`,he=document,Ae=()=>he.crea',
     '2)}$`,mn="?"+oe,Hr=`<${mn}>`,me=document,Ce=()=>me.crea'),
    # 058 rename
    ('t(""),Ce=e=>e',
     't(""),De=e=>e'),
    # 059 rename
    ('f\\r]`,De=/<(?',
     'f\\r]`,Ae=/<(?'),
    # 060 rename
    ('=/"/g,mn=/^(?',
     '=/"/g,hn=/^(?'),
    # 061 rename
    ('bt(1),Qo=bt(2),Jo=bt(3),me=Symb',
     'bt(1),Ji=bt(2),Qi=bt(3),he=Symb'),
    # 062 rename
    ('nge"),h=Symbo',
     'nge"),m=Symbo'),
    # 063 rename
    ('ap,pe=he.crea',
     'ap,pe=me.crea'),
    # 064 rename
    ('alker(he,129)',
     'alker(me,129)'),
    # 065 rename
    ('n}var Kr=(e,n',
     'n}var Br=(e,n'),
    # 066 rename
    ('=[],a,o=n===2',
     '=[],a,i=n===2'),
    # 067 rename
    ('>":"",i=De;for(',
     '>":"",o=Ae;for('),
    # 068 rename
    ('gth&&(i.lastI',
     'gth&&(o.lastI'),
    # 069 rename
    ('x=v,d=i.exec(',
     'x=v,d=o.exec('),
    # 070 rename
    ('l);)v=i.lastIndex,i===De?d[1]',
     'l);)v=o.lastIndex,o===Ae?d[1]'),
    # 071 rename
    ('"!--"?i=sn:d[',
     '"!--"?o=sn:d['),
    # 072 rename
    ('oid 0?i=ln:d[',
     'oid 0?o=ln:d['),
    # 073 rename
    ('id 0?(mn.test',
     'id 0?(hn.test'),
    # 074 rename
    ('"g")),i=ue):d',
     '"g")),o=ue):d'),
    # 075 rename
    ('d 0&&(i=ue):i===ue?',
     'd 0&&(o=ue):o===ue?'),
    # 076 rename
    ('=">"?(i=a??De,p=-1',
     '=">"?(o=a??Ae,p=-1'),
    # 077 rename
    ('-2:(p=i.lastI',
     '-2:(p=o.lastI'),
    # 078 rename
    ('=d[1],i=d[3]=',
     '=d[1],o=d[3]='),
    # 079 rename
    ('n:cn):i===dn||i===cn?i=ue:i===sn||i===ln?i=De:(i=ue,a=',
     'n:cn):o===dn||o===cn?o=ue:o===sn||o===ln?o=Ae:(o=ue,a='),
    # 080 rename
    ('let b=i===ue&',
     'let b=o===ue&'),
    # 081 rename
    (' ":"";o+=i===De?l+Hr',
     ' ":"";i+=o===Ae?l+Hr'),
    # 082 rename
    ('ce(p)+ie+b):l+ie+(p==',
     'ce(p)+oe+b):l+oe+(p=='),
    # 083 rename
    ('[fn(e,o+(e[t]',
     '[fn(e,i+(e[t]'),
    # 084 rename
    ('];let o=0,i=0,s=n',
     '];let i=0,o=0,s=n'),
    # 085 rename
    ('[c,d]=Kr(n,t)',
     '[c,d]=Br(n,t)'),
    # 086 rename
    ('t v=d[i++],b=',
     't v=d[o++],b='),
    # 087 rename
    ('split(ie),g=/',
     'split(oe),g=/'),
    # 088 rename
    ('index:o,name:',
     'index:i,name:'),
    # 089 rename
    ('=="@"?ht:_e})',
     '=="@"?mt:_e})'),
    # 090 rename
    ('sWith(ie)&&(l',
     'sWith(oe)&&(l'),
    # 091 rename
    ('index:o}),a.r',
     'index:i}),a.r'),
    # 092 rename
    ('));if(mn.test',
     '));if(hn.test'),
    # 093 rename
    ('split(ie),v=p',
     'split(oe),v=p'),
    # 094 rename
    ('(p[b],Ae()),p',
     '(p[b],Ce()),p'),
    # 095 rename
    ('dex:++o});a.a',
     'dex:++i});a.a'),
    # 096 rename
    ('(p[v],Ae())}}',
     '(p[v],Ce())}}'),
    # 097 rename
    ('ata===hn)l.pu',
     'ata===mn)l.pu'),
    # 098 rename
    ('index:o});els',
     'index:i});els'),
    # 099 rename
    ('dexOf(ie,p+1)',
     'dexOf(oe,p+1)'),
    # 100 rename
    ('index:o}),p+=ie.length-1}o++}}st',
     'index:i}),p+=oe.length-1}i++}}st'),
    # 101 rename
    ('let r=he.crea',
     'let r=me.crea'),
    # 102 rename
    ('f(n===me)retu',
     'f(n===he)retu'),
    # 103 rename
    ('._$Cl,o=Ce(n)?v',
     '._$Cl,i=De(n)?v'),
    # 104 rename
    ('tor!==o&&(a?.',
     'tor!==i&&(a?.'),
    # 105 rename
    ('.(!1),o===voi',
     '.(!1),i===voi'),
    # 106 rename
    ('a=new o(e),a.',
     'a=new i(e),a.'),
    # 107 rename
    ('cope??he).imp',
     'cope??me).imp'),
    # 108 rename
    ('a;let o=pe.ne',
     'a;let i=pe.ne'),
    # 109 rename
    ('ode(),i=0,s=0',
     'ode(),o=0,s=0'),
    # 110 rename
    (';){if(i===l.i',
     ';){if(o===l.i'),
    # 111 rename
    ('c=new Ie(o,o.nextS',
     'c=new Oe(i,i.nextS'),
    # 112 rename
    ('.ctor(o,l.nam',
     '.ctor(i,l.nam'),
    # 113 rename
    ('c=new mt(o,this,',
     'c=new ht(i,this,'),
    # 114 rename
    ('[++s]}i!==l?.',
     '[++s]}o!==l?.'),
    # 115 rename
    ('dex&&(o=pe.ne',
     'dex&&(i=pe.ne'),
    # 116 rename
    ('ode(),i++)}re',
     'ode(),o++)}re'),
    # 117 rename
    ('tNode=he,a}p(',
     'tNode=me,a}p('),
    # 118 rename
    ('t++}},Ie=clas',
     't++}},Oe=clas'),
    # 119 rename
    ('2,this._$AH=h,this._$AN=v',
     '2,this._$AH=m,this._$AN=v'),
    # 120 rename
    (',n,t),Ce(n)?n===h||n==n',
     ',n,t),De(n)?n===m||n==n'),
    # 121 rename
    ('$AH!==h&&this',
     '$AH!==m&&this'),
    # 122 rename
    ('._$AH=h):n!==',
     '._$AH=m):n!=='),
    # 123 rename
    ('&&n!==me&&thi',
     '&&n!==he&&thi'),
    # 124 rename
    ('$AH!==h&&Ce(this',
     '$AH!==m&&De(this'),
    # 125 rename
    ('his.T(he.crea',
     'his.T(me.crea'),
    # 126 rename
    ('e{let o=new d',
     'e{let i=new d'),
    # 127 rename
    ('this),i=o.u(thi',
     'this),o=i.u(thi'),
    # 128 rename
    ('ions);o.p(t),',
     'ions);i.p(t),'),
    # 129 rename
    ('his.T(i),this._$AH=o}}_$AC',
     'his.T(o),this._$AH=i}}_$AC'),
    # 130 rename
    ('r(let o of n)',
     'r(let i of n)'),
    # 131 rename
    ('his.O(Ae()),this.O(Ae()),t',
     'his.O(Ce()),this.O(Ce()),t'),
    # 132 rename
    ('._$AI(o),a++;',
     '._$AI(i),a++;'),
    # 133 rename
    ('t,r,a,o){this',
     't,r,a,i){this'),
    # 134 rename
    ('1,this._$AH=h,this._$AN=v',
     '1,this._$AH=m,this._$AN=v'),
    # 135 rename
    ('tions=o,r.len',
     'tions=i,r.len'),
    # 136 rename
    ('._$AH=h}_$AI(',
     '._$AH=m}_$AI('),
    # 137 rename
    ('is,r,a){let o=this.strings,i=!1;if(o===voi',
     'is,r,a){let i=this.strings,o=!1;if(i===voi'),
    # 138 rename
    (',t,0),i=!Ce(n)||',
     ',t,0),o=!De(n)||'),
    # 139 rename
    ('&&n!==me,i&&(thi',
     '&&n!==he,o&&(thi'),
    # 140 rename
    ('for(n=o[0],l=0;l<o.lengt',
     'for(n=i[0],l=0;l<i.lengt'),
    # 141 rename
    ('),c===me&&(c=',
     '),c===he&&(c='),
    # 142 rename
    ('H[l]),i||=!Ce(c)||',
     'H[l]),o||=!De(c)||'),
    # 143 rename
    ('],c===h?n=h:n!==h&&(n+=',
     '],c===m?n=m:n!==m&&(n+='),
    # 144 rename
    ('??"")+o[l+1])',
     '??"")+i[l+1])'),
    # 145 rename
    ('[l]=c}i&&!a&&',
     '[l]=c}o&&!a&&'),
    # 146 rename
    ('){n===h?this.',
     '){n===m?this.'),
    # 147 rename
    (']=n===h?void ',
     ']=n===m?void '),
    # 148 rename
    ('&&n!==h)}},ht=clas',
     '&&n!==m)}},mt=clas'),
    # 149 rename
    ('t,r,a,o){supe',
     't,r,a,i){supe'),
    # 150 rename
    ('t,r,a,o),this',
     't,r,a,i),this'),
    # 151 rename
    ('t,0)??h)===me)retu',
     't,0)??m)===he)retu'),
    # 152 rename
    ('a=n===h&&r!==h||n.ca',
     'a=n===m&&r!==m||n.ca'),
    # 153 rename
    ('ssive,o=n!==h&&(r===h||a);a',
     'ssive,i=n!==m&&(r===m||a);a'),
    # 154 rename
    ('is,r),o&&this',
     'is,r),i&&this'),
    # 155 rename
    ('(n)}},mt=clas',
     '(n)}},ht=clas'),
    # 156 rename
    ('};var Br=ft.l',
     '};var Kr=ft.l'),
    # 157 rename
    ('pport;Br?.(Ne,Ie),(ft',
     'pport;Kr?.(Ne,Oe),(ft'),
    # 158 rename
    ('){let o=t?.re',
     '){let i=t?.re'),
    # 159 rename
    ('a=new Ie(n.in',
     'a=new Oe(n.in'),
    # 160 rename
    ('efore(Ae(),o),o,void ',
     'efore(Ce(),i),i,void '),
    # 161 rename
    ('eturn me}};se',
     'eturn he}};se'),
    # 162 rename
    (':a}=t,o=globa',
     ':a}=t,i=globa'),
    # 163 rename
    ('a);if(o===voi',
     'a);if(i===voi'),
    # 164 rename
    ('set(a,o=new M',
     'set(a,i=new M'),
    # 165 rename
    ('d=!0),o.set(t',
     'd=!0),i.set(t'),
    # 166 rename
    ('"){let{name:i}=t;return{s',
     '"){let{name:o}=t;return{s'),
    # 167 rename
    ('questUpdate(i,l,e,!0,s)},',
     'questUpdate(o,l,e,!0,s)},'),
    # 168 rename
    ('his.C(i,void ',
     'his.C(o,void '),
    # 169 rename
    ('"){let{name:i}=t;return f',
     '"){let{name:o}=t;return f'),
    # 170 rename
    ('=this[i];n.ca',
     '=this[o];n.ca'),
    # 171 rename
    ('questUpdate(i,l,e,!0,s)}}',
     'questUpdate(o,l,e,!0,s)}}'),
    # 172 rename
    ('ction Qe(e){r',
     'ction Je(e){r'),
    # 173 rename
    ('((r,a,o)=>{let i=a.has',
     '((r,a,i)=>{let o=a.has'),
    # 174 rename
    ('perty(o);retu',
     'perty(i);retu'),
    # 175 rename
    ('perty(o,r),i?Objec',
     'perty(i,r),o?Objec'),
    # 176 rename
    ('tor(a,o):void',
     'tor(a,i):void'),
    # 177 rename
    ('ction V(e){return Qe({...',
     'ction U(e){return Je({...'),
    # 178 rename
    ('RED/i,Qr=/^(R',
     'RED/i,Jr=/^(R'),
    # 179 rename
    ('d":a&&Qr.test',
     'd":a&&Jr.test'),
    # 180 rename
    ('"}var Jr={una',
     '"}var Qr={una'),
    # 181 rename
    ('eturn Jr[e]}v',
     'eturn Qr[e]}v'),
    # 182 rename
    ('sText:o}=e;re',
     'sText:i}=e;re'),
    # 183 rename
    ('able":o&&Zr.test(o)?"rec',
     'able":i&&Zr.test(i)?"rec'),
    # 184 rename
    ('tion":o&&ea.test(o)?"def',
     'tion":i&&ea.test(i)?"def'),
    # 185 rename
    ('rred":o&&ta.test(o)?"bus',
     'rred":i&&ta.test(i)?"bus'),
    # 186 rename
    ('ort/i,oa=/Sto',
     'ort/i,ia=/Sto'),
    # 187 rename
    ('t t=n?oa.exec',
     't t=n?ia.exec'),
    # 188 rename
    ('l}var ia=/OPE',
     'l}var oa=/OPE'),
    # 189 rename
    ('&!!e&&ia.test',
     '&!!e&&oa.test'),
    # 190 rename
    ('ned/i,ha=/RES',
     'ned/i,ma=/RES'),
    # 191 rename
    ('null}:ha.test',
     'null}:ma.test'),
    # 192 rename
    ('}}var ma=new ',
     '}}var ha=new '),
    # 193 rename
    ('null&&ma.has(',
     'null&&ha.has('),
    # 194 rename
    ('ction Oe(e,n)',
     'ction Ie(e,n)'),
    # 195 rename
    ('}}var Rn=["re',
     '}}var Pn=["re'),
    # 196 rename
    ('ction Pn(e){let n=Rn.inde',
     'ction Rn(e){let n=Pn.inde'),
    # 197 rename
    ('n n<0?Rn.leng',
     'n n<0?Pn.leng'),
    # 198 rename
    ('eturn Pn(n)<Pn(e)?"',
     'eturn Rn(n)<Rn(e)?"'),
    # 199 rename
    ('r"}function Dn(e){switch(',
     'r"}function An(e){switch('),
    # 200 rename
    ('"}}function An(e){switch(',
     '"}}function Cn(e){switch('),
    # 201 rename
    ('ction Cn(e){r',
     'ction Dn(e){r'),
    # 202 rename
    ('))}function Rt(e){return!',
     '))}function Pt(e){return!'),
    # 203 rename
    ('))}function Pt(e){return ',
     '))}function Rt(e){return '),
    # 204 rename
    (':e}function Dt(e){return{',
     ':e}function At(e){return{'),
    # 205 rename
    ('}}}function At(e){return{',
     '}}}function Ct(e){return{'),
    # 206 rename
    ('y_id:e}}}function In(e,n){return{doma',
     'y_id:e}}}function On(e,n){return{doma'),
    # 207 rename
    ('ction Ct(e,n)',
     'ction Dt(e,n)'),
    # 208 rename
    ('alue:n}}}function On(e,n){return n===',
     'alue:n}}}function In(e,n){return n==='),
    # 209 rename
    ('t,r,a,o,i,s]=n,',
     't,r,a,i,o,s]=n,'),
    # 210 rename
    ('umber(o),Number(i),Numb',
     'umber(i),Number(o),Numb'),
    # 211 rename
    (',"0"),o=e.get',
     ',"0"),i=e.get'),
    # 212 rename
    ('{a}:${o}`}fun',
     '{a}:${i}`}fun'),
    # 213 rename
    ('3600),o=Math.',
     '3600),i=Math.'),
    # 214 rename
    ('0/60),i=r%60;',
     '0/60),o=r%60;'),
    # 215 rename
    ('a}h ${o}m`:o>0?`${o}m ${i.toStr',
     'a}h ${i}m`:i>0?`${i}m ${o.toStr'),
    # 216 rename
    ('s`:`${i}s`}fu',
     's`:`${o}s`}fu'),
    # 217 rename
    ('ction K(e,n){',
     'ction B(e,n){'),
    # 218 rename
    ('ction B(e){le',
     'ction K(e){le'),
    # 219 rename
    ('let r=K(e,t.c',
     'let r=B(e,t.c'),
    # 220 rename
    ('1}var qi=Objec',
     '1}var Xo=Objec'),
    # 221 rename
    ('e:1}),It=["MI',
     'e:1}),Ot=["MI'),
    # 222 rename
    ('IED"],m=Objec',
     'IED"],h=Objec'),
    # 223 rename
    ('100}),J={"cha',
     '100}),Q={"cha'),
    # 224 rename
    ('nit:"%",min:m.chargeTargetMin,max:m.chargeTarge',
     'nit:"%",min:h.chargeTargetMin,max:h.chargeTarge'),
    # 225 rename
    ('",min:m.buffe',
     '",min:h.buffe'),
    # 226 rename
    ('n,max:m.buffe',
     'n,max:h.buffe'),
    # 227 rename
    ('nit:"W",min:m.chargePowerMin,max:m.chargePower',
     'nit:"W",min:h.chargePowerMin,max:h.chargePower'),
    # 228 rename
    ('",min:m.stopS',
     '",min:h.stopS'),
    # 229 rename
    ('n,max:m.stopS',
     'n,max:h.stopS'),
    # 230 rename
    ('nit:"W",min:m.exportPowerMin,max:m.exportPower',
     'nit:"W",min:h.exportPowerMin,max:h.exportPower'),
    # 231 rename
    ('t:"min",min:m.exportDurationMin,max:m.exportDurat',
     't:"min",min:h.exportDurationMin,max:h.exportDurat'),
    # 232 rename
    ('ed)",unit:"%",min:m.reserveMin,max:m.reserveMax,step:1',
     'ed)",unit:"%",min:h.reserveMin,max:h.reserveMax,step:1'),
    # 233 rename
    ('ce)",unit:"%",min:m.reserveMin,max:m.reserveMax,step:1',
     'ce)",unit:"%",min:h.reserveMin,max:h.reserveMax,step:1'),
    # 234 rename
    ('.keys(J));function Ve(e,n)',
     '.keys(Q));function Ue(e,n)'),
    # 235 rename
    ('.call(J,e))re',
     '.call(Q,e))re'),
    # 236 rename
    ('let t=J[e];if',
     'let t=Q[e];if'),
    # 237 rename
    ('ction Vn(e,n=',
     'ction Un(e,n='),
    # 238 rename
    ('let a=Ve(r,e[',
     'let a=Ue(r,e['),
    # 239 rename
    (' 0?[]:J[e].vi',
     ' 0?[]:Q[e].vi'),
    # 240 rename
    ('s.map(o=>({view:o,path:',
     's.map(i=>({view:i,path:'),
    # 241 rename
    ('.call(J,n.pat',
     '.call(Q,n.pat'),
    # 242 rename
    (');let o=Ve(n.pa',
     ');let i=Ue(n.pa'),
    # 243 rename
    ('eturn o.ok?r.',
     'eturn i.ok?r.'),
    # 244 rename
    ('ence"?o.value',
     'ence"?i.value'),
    # 245 rename
    ('value:o.value',
     'value:i.value'),
    # 246 rename
    ('l")}):o.value',
     'l")}):i.value'),
    # 247 rename
    ('value=o.value',
     'value=i.value'),
    # 248 rename
    ('ved===o.value',
     'ved===i.value'),
    # 249 rename
    ('lue===o.value',
     'lue===i.value'),
    # 250 rename
    ('):L(e,o.error',
     '):L(e,i.error'),
    # 251 rename
    (':{let o=r.observed,i=n.obs',
     ':{let i=r.observed,o=n.obs'),
    # 252 rename
    ('eturn i!==nul',
     'eturn o!==nul'),
    # 253 rename
    ('inite(i)?L(e,',
     'inite(o)?L(e,'),
    # 254 rename
    ('ll."):i===o?{ok:!',
     'll."):o===i?{ok:!'),
    # 255 rename
    ('erved=i,i===nul',
     'erved=o,o===nul'),
    # 256 rename
    ('SED"):i===r.v',
     'SED"):o===r.v'),
    # 257 rename
    ('TCH"||o!==null&&o!==i)&&(r.',
     'TCH"||i!==null&&i!==o)&&(r.'),
    # 258 rename
    ('value:i,revis',
     'value:o,revis'),
    # 259 rename
    ('){let o=Ve(n.pa',
     '){let i=Ue(n.pa'),
    # 260 rename
    ('.value);if(!o.ok)return L',
     '.value);if(!i.ok)return L'),
    # 261 rename
    ('ts ("+o.error',
     'ts ("+i.error'),
    # 262 rename
    ('ction Un(e,n)',
     'ction Vn(e,n)'),
    # 263 rename
    ('let t=It.leng',
     'let t=Ot.leng'),
    # 264 rename
    ('min(t,It.inde',
     'min(t,Ot.inde'),
    # 265 rename
    ('eturn It[t]??',
     'eturn Ot[t]??'),
    # 266 rename
    ('gth!==m.slots',
     'gth!==h.slots'),
    # 267 rename
    ('t=0;t<m.slots',
     't=0;t<h.slots'),
    # 268 rename
    ('(t+1)%m.slots',
     '(t+1)%h.slots'),
    # 269 rename
    ('rtMin,o=K(r,a);if(o<m.minSl',
     'rtMin,i=B(r,a);if(i<h.minSl'),
    # 270 rename
    ('"};n+=o}retur',
     '"};n+=i}retur'),
    # 271 rename
    ('ction Ot(e,n)',
     'ction It(e,n)'),
    # 272 rename
    ('t,r)=>Ot(t,n[',
     't,r)=>It(t,n['),
    # 273 rename
    (')}var Ue=1440',
     ')}var Ve=1440'),
    # 274 rename
    ('t=0;t<Ue;t++)',
     't=0;t<Ve;t++)'),
    # 275 rename
    ('r(let o=0;o<e.length;o++){let i=e[o],s=e[(o+1)%e.',
     'r(let i=0;i<e.length;i++){let o=e[i],s=e[(i+1)%e.'),
    # 276 rename
    ('h];if(K(i.start',
     'h];if(B(o.start'),
    # 277 rename
    ('in,r)<K(i.start',
     'in,r)<B(o.start'),
    # 278 rename
    ('n)){a=i;break',
     'n)){a=o;break'),
    # 279 rename
    ('e.map(o=>({...o}));re',
     'e.map(i=>({...i}));re'),
    # 280 rename
    ('>{let o=t&&t.',
     '>{let i=t&&t.'),
    # 281 rename
    (':null,i=o===nul',
     ':null,o=i===nul'),
    # 282 rename
    ('OSED":Ot(o,r)?"A',
     'OSED":It(i,r)?"A'),
    # 283 rename
    ('erved:o?{...o}:null',
     'erved:i?{...i}:null'),
    # 284 rename
    ('state:i}})}function Kn(e,n){let t',
     'state:o}})}function Bn(e,n){let t'),
    # 285 rename
    ('>{let o=e&&e.',
     '>{let i=e&&e.'),
    # 286 rename
    (':null,i=["sta',
     ':null,o=["sta'),
    # 287 rename
    (' s of i)(o===null||o[s]!==',
     ' s of o)(i===null||i[s]!=='),
    # 288 rename
    (',from:o===nul',
     ',from:i===nul'),
    # 289 rename
    ('?null:o[s],to',
     '?null:i[s],to'),
    # 290 rename
    ('onMin<m.minSl',
     'onMin<h.minSl'),
    # 291 rename
    ('etSoc<m.stopS',
     'etSoc<h.stopS'),
    # 292 rename
    ('etSoc>m.stopS',
     'etSoc>h.stopS'),
    # 293 rename
    (' be "+m.stopS',
     ' be "+h.stopS'),
    # 294 rename
    ('n+"-"+m.stopS',
     'n+"-"+h.stopS'),
    # 295 rename
    ('owerW<m.expor',
     'owerW<h.expor'),
    # 296 rename
    ('owerW>m.expor',
     'owerW>h.expor'),
    # 297 rename
    ('ide "+m.expor',
     'ide "+h.expor'),
    # 298 rename
    ('n+"-"+m.expor',
     'n+"-"+h.expor'),
    # 299 rename
    ('etSoc<m.charg',
     'etSoc<h.charg'),
    # 300 rename
    ('etSoc>m.charg',
     'etSoc>h.charg'),
    # 301 rename
    ('s outside "+m.chargeTargetMin+"-"+m.chargeTarge',
     's outside "+h.chargeTargetMin+"-"+h.chargeTarge'),
    # 302 rename
    ('owerW<m.charg',
     'owerW<h.charg'),
    # 303 rename
    ('owerW>m.charg',
     'owerW>h.charg'),
    # 304 rename
    ('s outside "+m.chargePowerMin+"-"+m.chargePower',
     's outside "+h.chargePowerMin+"-"+h.chargePower'),
    # 305 rename
    ('h;r++)Ot(e[r]',
     'h;r++)It(e[r]'),
    # 306 rename
    ('){let D=Kn(w,e.',
     '){let A=Bn(w,e.'),
    # 307 rename
    ('+" ("+D.lengt',
     '+" ("+A.lengt'),
    # 308 rename
    ('lot "+D[0].sl',
     'lot "+A[0].sl'),
    # 309 rename
    ('t+" "+D[0].fi',
     't+" "+A[0].fi'),
    # 310 rename
    (' a=[],o=e.int',
     ' a=[],i=e.int'),
    # 311 rename
    ('or(let f of o){let w=ya(f',
     'or(let f of i){let w=ya(f'),
    # 312 rename
    ('})}if(o.filte',
     '})}if(i.filte'),
    # 313 rename
    ('th>1||o.filte',
     'th>1||i.filte'),
    # 314 rename
    (');let i=o.find(',
     ');let o=i.find('),
    # 315 rename
    ('e"),s=o.find(',
     'e"),s=i.find('),
    # 316 rename
    ('");if(i&&s){let f=K(s.sta',
     '");if(o&&s){let f=B(s.sta'),
    # 317 rename
    ('onMin,i.start',
     'onMin,o.start'),
    # 318 rename
    ('in),w=K(i.startMin+i.durat',
     'in),w=B(o.startMin+o.durat'),
    # 319 rename
    ('n);if(K(i.start',
     'n);if(B(o.start'),
    # 320 rename
    ('tMin)<i.durat',
     'tMin)<o.durat'),
    # 321 rename
    ('nMin||K(s.startMin,i.start',
     'nMin||B(s.startMin,o.start'),
    # 322 rename
    ('or(let f of o){let w=re(f',
     'or(let f of i){let w=re(f'),
    # 323 rename
    ('or(let f of o){let w=xa(f',
     'or(let f of i){let w=xa(f'),
    # 324 rename
    ('r(let D=0;D<f.dur',
     'r(let A=0;A<f.dur'),
    # 325 rename
    ('onMin;D+=5)c[',
     'onMin;A+=5)c['),
    # 326 rename
    ('rtMin+D)/5%Ue]={..',
     'rtMin+A)/5%Ve]={..'),
    # 327 rename
    ('f=0;f<Ue;f++)',
     'f=0;f<Ve;f++)'),
    # 328 rename
    ('=c[(f+Ue-1)%Ue];Gn(',
     '=c[(f+Ve-1)%Ve];Gn('),
    # 329 rename
    (';if(p>m.slots',
     ';if(p>h.slots'),
    # 330 rename
    ('ap(f=>B(f)).j',
     'ap(f=>K(f)).j'),
    # 331 rename
    ('tly "+m.slots',
     'tly "+h.slots'),
    # 332 rename
    ('rvals:Bn(o,n)});',
     'rvals:Kn(i,n)});'),
    # 333 rename
    ('ngth>=m.slots',
     'ngth>=h.slots'),
    # 334 rename
    ('ength<m.slots',
     'ength<h.slots'),
    # 335 rename
    ('let T=K(d[$],',
     'let T=B(d[$],'),
    # 336 rename
    (')}let D=re(d[',
     ')}let A=re(d['),
    # 337 rename
    ('.push(D),d.so',
     '.push(A),d.so'),
    # 338 rename
    ('>{let D=K(f,w)|',
     '>{let A=B(f,w)|'),
    # 339 rename
    ('$=0;$<D;$+=5)',
     '$=0;$<A;$+=5)'),
    # 340 rename
    ('},_=0,R=1/0;f',
     '},_=0,P=1/0;f'),
    # 341 rename
    ('f=0;f<m.slots',
     'f=0;f<h.slots'),
    # 342 rename
    ('(T+f)%m.slots]),D=Sa(w,',
     '(T+f)%h.slots]),A=Sa(w,'),
    # 343 rename
    ('line);D<R&&(R=D,_=f)}',
     'line);A<P&&(P=A,_=f)}'),
    # 344 rename
    ('(w+_)%m.slots]})),C=g.map',
     '(w+_)%h.slots]})),D=g.map'),
    # 345 rename
    ('>{let D=(w+_)%m.slots',
     '>{let A=(w+_)%h.slots'),
    # 346 rename
    ('n E(g[D].star',
     'n E(g[A].star'),
    # 347 rename
    ('in,g[(D+1)%m.slots',
     'in,g[(A+1)%h.slots'),
    # 348 rename
    ('in)}),P=ye(x);if(!P.ok)re',
     'in)}),R=ye(x);if(!R.ok)re'),
    # 349 rename
    ('ed ("+P.why+"',
     'ed ("+R.why+"'),
    # 350 rename
    (':jn(x,C,e.obs',
     ':jn(x,D,e.obs'),
    # 351 rename
    ('edits:Kn(e.ob',
     'edits:Bn(e.ob'),
    # 352 rename
    ('rvals:Bn(o,n),re',
     'rvals:Kn(i,n),re'),
    # 353 rename
    ('1}}function Bn(e,n){retur',
     '1}}function Kn(e,n){retur'),
    # 354 rename
    ('};let o=r.max',
     '};let i=r.max'),
    # 355 rename
    (';if(a>o)retur',
     ';if(a>i)retur'),
    # 356 rename
    ('ost "+o+" min',
     'ost "+i+" min'),
    # 357 rename
    ('};let i={kind',
     '};let o={kind'),
    # 358 rename
    ('s)||s<m.reserveMin||s>m.reserveMax)',
     's)||s<h.reserveMin||s>h.reserveMax)'),
    # 359 rename
    ('reserve must be "+m.reserveMin+"-"+m.reserveMax+" %.",',
     'reserve must be "+h.reserveMin+"-"+h.reserveMax+" %.",'),
    # 360 rename
    ('NGE"};i.reser',
     'NGE"};o.reser'),
    # 361 rename
    ('rride:i}}var ',
     'rride:o}}var '),
    # 362 rename
    ('=n%60,o=[];re',
     '=n%60,i=[];re'),
    # 363 rename
    (' t>0&&o.push(',
     ' t>0&&i.push('),
    # 364 rename
    (',r>0&&o.push(',
     ',r>0&&i.push('),
    # 365 rename
    (',a>0&&o.push(',
     ',a>0&&i.push('),
    # 366 rename
    ('min"),o.join(',
     'min"),i.join('),
    # 367 rename
    ('eturn B(n);le',
     'eturn K(n);le'),
    # 368 rename
    (')}let o=a.min',
     ')}let i=a.min'),
    # 369 rename
    ('ryMin,i=(d,p,v)=>{o!==voi',
     'ryMin,o=(d,p,v)=>{i!==voi'),
    # 370 rename
    (' 0&&p<o&&t.pu',
     ' 0&&p<i&&t.pu'),
    # 371 rename
    ('m.")};i("Hold',
     'm.")};o("Hold'),
    # 372 rename
    ('pMin),i("Prep',
     'pMin),o("Prep'),
    # 373 rename
    ('pMin),o!==voi',
     'pMin),i!==voi'),
    # 374 rename
    ('apMin<o&&t.pu',
     'apMin<i&&t.pu'),
    # 375 rename
    ('0&&(s<m.reserveMin||s>m.reserveMax)',
     '0&&(s<h.reserveMin||s>h.reserveMax)'),
    # 376 rename
    ('reserve must be "+m.reserveMin+"-"+m.reserveMax+" %.")',
     'reserve must be "+h.reserveMin+"-"+h.reserveMax+" %.")'),
    # 377 rename
    ('let r=K(e,n),',
     'let r=B(e,n),'),
    # 378 rename
    ('440:r,o=Fe(e,',
     '440:r,i=Fe(e,'),
    # 379 rename
    ('eturn o>0?{ok',
     'eturn i>0?{ok'),
    # 380 rename
    ('ryMin:o}:{ok:',
     'ryMin:i}:{ok:'),
    # 381 rename
    ('ction Ra(e,n)',
     'ction Pa(e,n)'),
    # 382 rename
    ('}}var Pa=[30,',
     '}}var Ra=[30,'),
    # 383 rename
    ('0];function Qn(e,n,t){let',
     '0];function Jn(e,n,t){let'),
    # 384 rename
    (':null,o=new S',
     ':null,i=new S'),
    # 385 rename
    (' s of Pa)s>=n',
     ' s of Ra)s>=n'),
    # 386 rename
    ('s<=r&&o.add(s',
     's<=r&&i.add(s'),
    # 387 rename
    ('null&&o.add(a),o.add(r);let i=[...o].filt',
     'null&&i.add(a),i.add(r);let o=[...i].filt'),
    # 388 rename
    ('n<=r&&i.push(',
     'n<=r&&o.push('),
    # 389 rename
    ('til "+B(n.ski',
     'til "+K(n.ski'),
    # 390 rename
    ('eturn i.sort(',
     'eturn o.sort('),
    # 391 rename
    ('))}function Jn(e,n,t,r,a)',
     '))}function Qn(e,n,t,r,a)'),
    # 392 rename
    ('};let o=r.con',
     '};let i=r.con'),
    # 393 rename
    ('"};if(o.cutRe',
     '"};if(i.cutRe'),
    # 394 rename
    ('ve ("+o.cutRe',
     've ("+i.cutRe'),
    # 395 rename
    ('}}let i=Yn(e,n,t,Ra(o,a.clo',
     '}}let o=Yn(e,n,t,Pa(i,a.clo'),
    # 396 rename
    (');if(!i.ok)return i;let s=i.overr',
     ');if(!o.ok)return o;let s=o.overr'),
    # 397 rename
    ('AtMin-i.overr',
     'AtMin-o.overr'),
    # 398 rename
    ('ING"}:i}var T',
     'ING"}:o}var T'),
    # 399 rename
    (');var Da=["HI',
     ');var Aa=["HI'),
    # 400 rename
    ('}}var Aa=["ch',
     '}}var Ca=["ch'),
    # 401 rename
    (',a=[],o="UNKN',
     ',a=[],i="UNKN'),
    # 402 rename
    ('ing"&&Da.incl',
     'ing"&&Aa.incl'),
    # 403 rename
    ('ce)&&(o=n.con',
     'ce)&&(i=n.con'),
    # 404 rename
    (');let i={known:o!=="UN',
     ');let o={known:i!=="UN'),
    # 405 rename
    ('level:o,state',
     'level:i,state'),
    # 406 rename
    ('state:Un(t,Aa),ori',
     'state:Vn(t,Ca),ori'),
    # 407 rename
    (')."}),i.known?o!=="HI',
     ')."}),o.known?i!=="HI'),
    # 408 rename
    (' is "+o+": EC',
     ' is "+i+": EC'),
    # 409 rename
    ('dence:i,why:a}}var Ca=60,gs=Obje',
     'dence:o,why:a}}var Da=60,vs=Obje'),
    # 410 rename
    ('erMin:m.buffe',
     'erMin:h.buffe'),
    # 411 rename
    ('erMax:m.buffe',
     'erMax:h.buffe'),
    # 412 model
    ('x:15});var Na=Obje',
     'x:15}),Na="max_charge_power_effective",_s=Object.freeze({name:Na,kind:"SETPOINT_BOUND",authoritativeW:h.chargePowerMax,effectiveRule:"min(firmware setpoint bound, owner operating limit); unknown when either is unknown",source:"the firmware slot-power bound (compile time) and the owner\'s grid charge operating limit helper; the planner\'s effective maximum grid charge power figure",isNot:Object.freeze(["a measured battery-side charge power (the realised power was above it on the nights checked)","the grid import limit (the import was above it, and it is separate and unknown)","the inverter\'s rated power or the battery\'s own current limit","a BMS limit or a derating"]),confidence:"Established by code for what it is; the realised power against it is established by saved data for one setpoint only; the setpoint unit stays UNSETTLED"});var ws=Object.freeze({UNCONSTRAINED:Object.freeze({id:"UNCONSTRAINED",label:"No path assumed (the generic model)",setpointUnit:"W (generic)",stepW:100,minW:h.chargePowerMin,maxW:h.chargePowerMax,minDwellMin:0,maxAdjustmentsPerWindow:100,midWindowAdjustment:!0,ownerConfirmationPerChange:!1,existsToday:!1,automaticApplyAuthorised:!1,limitation:"No path is assumed: the generic model\'s own parameters apply unchanged.",source:"the model\'s defaults",confidence:"NOT_BUILT"}),FREE_POWER_LEASE:Object.freeze({id:"FREE_POWER_LEASE",label:"Free Power start (a fixed rate for a duration)",setpointUnit:"W, staged once; the firmware turns it into a grid-charge current at the battery voltage of that moment and sets the slot powers to it",stepW:100,minW:h.chargePowerMin,maxW:h.chargePowerMax,minDwellMin:0,maxAdjustmentsPerWindow:0,midWindowAdjustment:!1,ownerConfirmationPerChange:!1,existsToday:!0,automaticApplyAuthorised:!1,limitation:"The rate is fixed at the START and verified against; a change from outside during a lease blocks the automatic restore; there is no stop at a target SOC.",source:"firmware Free Power START and restore classifier; docs/product-ui/FEASIBILITY_MATRIX.md 2.2",confidence:"CODE"}),TOU_SLOT_EDITOR:Object.freeze({id:"TOU_SLOT_EDITOR",label:"Guarded TOU slot editor (slot power), owner confirms each write",setpointUnit:"W, the slot power setting (a multiple of 100, 500 to the firmware bound)",stepW:100,minW:h.chargePowerMin,maxW:h.chargePowerMax,minDwellMin:60,maxAdjustmentsPerWindow:1,midWindowAdjustment:!0,ownerConfirmationPerChange:!0,existsToday:!0,automaticApplyAuthorised:!1,limitation:"One field of one slot per request through Review, a typed confirmation and Apply; no durable snapshot and no rollback; refused near slot boundaries, in a lease and on clock-change nights; no live proof of a charge-rate response below the top rate.",source:"the TOU editor package and docs (one field per request, 500 to 8000 W in steps of 100); dwell and adjustment count are PROPOSED policy, not device limits",confidence:"CODE for the range and step; PROPOSED_POLICY for dwell and count"}),RATE_CONTROLLER_PROPOSED:Object.freeze({id:"RATE_CONTROLLER_PROPOSED",label:"A guarded rate controller (does not exist)",setpointUnit:"W, the slot power setting, changed by a firmware controller on the Dump to Grid V1.1 pattern",stepW:100,minW:h.chargePowerMin,maxW:h.chargePowerMax,minDwellMin:30,maxAdjustmentsPerWindow:6,midWindowAdjustment:!0,ownerConfirmationPerChange:!1,existsToday:!1,automaticApplyAuthorised:!1,limitation:"Not built, not reviewed, not proven: the proof list in GENTLE_LIVE_ACTUATION_PROOF.md must exist first.",source:"docs/product-ui/FEASIBILITY_MATRIX.md 2.2 (the Dump V1.1 limits are the template); the numbers are the model\'s own proposals",confidence:"NOT_BUILT"})});var Oa=Obje'),
    # 413 rename
    ('e({stepW:100,minW:m.chargePowerMin,ha',
     'e({stepW:100,minW:h.chargePowerMin,ha'),
    # 414 rename
    ('dMaxW:m.charg',
     'dMaxW:h.charg'),
    # 415 model
    ('in:20,demand',
     'in:20,socRegressionTolPct:3,socJumpPctPerHour:60,demand'),
    # 416 model
    ('W:2e3,maxHou',
     'W:2e3,solarCreditPct:0,maxHou'),
    # 417 model
    ('in:15,maxDec',
     'in:15,setpointConversionEff:.85,maxForecastAgeMin:120,maxCeilingAgeMin:60,maxGridLimitAgeMin:60,maxDec'),
    # 418 rename
    ('StepW:m.charg',
     'StepW:h.charg'),
    # 419 model
    ('werMax}),bs=Obje',
     'werMax,setpointOvershoot:1}),xs=Obje'),
    # 420 model
    ('pW:1e3}),Ia=',
     'pW:1e3,setpointOvershoot:1.1}),Ia='),
    # 421 model
    ('licy:"ASSUME_PROVISIONAL"}),tr',
     'licy:"FALLBACK",setpointBasis:"UNSETTLED",actuatorProfile:"UNCONSTRAINED"}),tr'),
    # 422 model
    ('rge"],demand',
     'rge"],socRegressionTolPct:["PROVISIONAL","the measured noise and update behaviour of the SOC sensor"],socJumpPctPerHour:["PROVISIONAL","the measured fastest real charge rate of the battery"],demand'),
    # 423 model
    ('ay)"],maxHou',
     'ay)"],solarCreditPct:["PROVISIONAL","a measured forecast skill gate (none exists: 0 means no solar inside the hard grid limit)"],maxHou'),
    # 424 model
    ('ensors"],max',
     'ensors"],setpointConversionEff:["PROVISIONAL","the measured grid-to-battery power ratio at the settled setpoint basis (unmeasured; pessimistic by design)"],maxForecastAgeMin:["PROVISIONAL","the real refresh rate of the demand and solar forecasts"],maxCeilingAgeMin:["PROVISIONAL","the real update rate of the live battery and grid-charge limits"],maxGridLimitAgeMin:["PROVISIONAL","the real update rate of the grid import limit, when it is read from a device"],max'),
    # 425 model
    ('ice"],target',
     'ice"],setpointBasis:["PROVISIONAL","live proof of what the actuator\'s setpoint means: AC grid watts or DC battery watts"],actuatorProfile:["PROVISIONAL","the owner\'s decision on which one path may later apply a recommendation (none is authorised today)"],setpointOvershoot:["PROVISIONAL","commanded setpoint against measured battery-side and grid-side power at several setpoints (the saved nights hold one setpoint only, and the real power was above it)"],target'),
    # 426 model
    ('buffer"],gri',
     'buffer (60 minutes when not given)"],gri'),
    # 427 rename
    ('ction Oa(){le',
     'ction $a(){le'),
    # 428 rename
    ('n={...Na,...I',
     'n={...Oa,...I'),
    # 429 rename
    ('erMin:Ca,grid',
     'erMin:Da,grid'),
    # 430 rename
    (')}var vs=Oa(),_s=2*14',
     ')}var ys=$a(),Ss=2*14'),
    # 431 rename
    ('0;var $a=Obje',
     '0;var La=Obje'),
    # 432 rename
    ('ed"}),La=6,Wa=/^[+',
     'ed"}),Wa=6,Fa=/^[+'),
    # 433 rename
    ('+)?$/,Fa=/^(\\',
     '+)?$/,Ua=/^(\\'),
    # 434 rename
    (');if(!Wa.test',
     ');if(!Fa.test'),
    # 435 rename
    ('ction Ua(e){i',
     'ction Ha(e){i'),
    # 436 rename
    ('let n=Fa.exec',
     'let n=Ua.exec'),
    # 437 rename
    ('ction Ha(e,n)',
     'ction Ga(e,n)'),
    # 438 rename
    ('ction Ga(e){r',
     'ction Ba(e){r'),
    # 439 rename
    ('arget,o=Wt(e,',
     'arget,i=Wt(e,'),
    # 440 rename
    ('dvice,i=o&&typeof o=="obj',
     'dvice,o=i&&typeof i=="obj'),
    # 441 rename
    ('Array(o)?o:{},s=',
     'Array(i)?i:{},s='),
    # 442 rename
    (',a),d=i.bindi',
     ',a),d=o.bindi'),
    # 443 rename
    ('+"."),i.conse',
     '+"."),o.conse'),
    # 444 rename
    (' p=rr(i.net_n',
     ' p=rr(o.net_n'),
    # 445 rename
    ('wh:rr(i.grid_',
     'wh:rr(o.grid_'),
    # 446 rename
    ('c}}function Ba(e,n){let t',
     'c}}function ja(e,n){let t'),
    # 447 rename
    ('r(let o=1;o<=La;o++){let i=Ha(n,o),s=Ua(G(e,i.time)',
     'r(let i=1;i<=Wa;i++){let o=Ga(n,i),s=Ha(G(e,o.time)'),
    # 448 rename
    ('l=M(e,i.power',
     'l=M(e,o.power'),
    # 449 rename
    ('c=M(e,i.soc),d=G(e,i.charg',
     'c=M(e,o.soc),d=G(e,o.charg'),
    # 450 rename
    ('lot "+o+" "+p',
     'lot "+i+" "+p'),
    # 451 rename
    ('00;function ja(e,n){if(!n',
     '00;function za(e,n){if(!n'),
    # 452 rename
    ('ction oe(e,n,',
     'ction ie(e,n,'),
    # 453 rename
    ('let a=Ve(e,n)',
     'let a=Ue(e,n)'),
    # 454 rename
    ('edule,o=e.dum',
     'edule,i=e.dum'),
    # 455 rename
    ('_grid,i=o?.sche',
     '_grid,o=i?.sche'),
    # 456 rename
    ('l={...$a,...t',
     'l={...La,...t'),
    # 457 rename
    ('),d=s?Ba(n,s)',
     '),d=s?ja(n,s)'),
    # 458 rename
    (':null,R=a?M(n',
     ':null,P=a?M(n'),
    # 459 rename
    ('erW"]=oe("charge.powerW",R,"The charge',
     'erW"]=ie("charge.powerW",P,"The charge'),
    # 460 rename
    ('wStartMin"]=oe("charge.wi',
     'wStartMin"]=ie("charge.wi'),
    # 461 rename
    ('dowEndMin"]=oe("charge.wi',
     'dowEndMin"]=ie("charge.wi'),
    # 462 rename
    ('Soc"]=oe("cha',
     'Soc"]=ie("cha'),
    # 463 rename
    ('};let C=o?j(n,o.active):!1,P=i?M(n,i.power):o?M(n,o.expor',
     '};let D=i?j(n,i.active):!1,R=o?M(n,o.power):i?M(n,i.expor'),
    # 464 rename
    ('ull,W=i?M(n,',
     'ull,W=o?M(n,o.stop_soc):i?M(n,'),
    # 465 rename
    ('_soc):o?M(n,o.stop_soc):null,f=o&&C?M(n,o.activ',
     '_soc):null,f=i&&D?M(n,i.activ'),
    # 466 rename
    ('ull,w=o&&C?M(n,o.activ',
     'ull,w=i&&D?M(n,i.activ'),
    # 467 rename
    (':null,D=i?nr(G(n,i.start',
     ':null,A=o?nr(G(n,o.start'),
    # 468 rename
    ('ull,$=i?M(n,i.duration):o?M(n,o.durat',
     'ull,$=o?M(n,o.duration):i?M(n,i.durat'),
    # 469 rename
    ('erW"]=oe("export.powerW",P,"The export',
     'erW"]=ie("export.powerW",R,"The export'),
    # 470 rename
    ('Soc"]=oe("exp',
     'Soc"]=ie("exp'),
    # 471 rename
    ('.startMin"]=oe("export.st',
     '.startMin"]=ie("export.st'),
    # 472 rename
    ('tMin",D,i?"The ',
     'tMin",A,o?"The '),
    # 473 rename
    ('rationMin"]=oe("export.du',
     'rationMin"]=ie("export.du'),
    # 474 rename
    ('let T=ja(n,t.',
     'let T=za(n,t.'),
    # 475 rename
    ('known?oe("res',
     'known?ie("res'),
    # 476 rename
    ('value:J[k].min;let Q=Vn(ke,"',
     'value:Q[k].min;let J=Un(ke,"'),
    # 477 rename
    ('ner"),Bt=a?j(',
     'ner"),Kt=a?j('),
    # 478 rename
    ('d):!1,ot=r?j(',
     'd):!1,it=r?j('),
    # 479 rename
    ('!1,jt=i?j(n,i.armed',
     '!1,jt=o?j(n,o.armed'),
    # 480 rename
    ('Min"],Dr=["ex',
     'Min"],Ar=["ex'),
    # 481 rename
    ('Min"],it=(k,N',
     'Min"],ot=(k,N'),
    # 482 rename
    ('=>{let F=nt(Q,{type:N,pat',
     '=>{let F=nt(J,{type:N,pat'),
    # 483 rename
    (':k});F.ok&&(Q=F.settings)',
     ':k});F.ok&&(J=F.settings)'),
    # 484 rename
    ('r(let I of k)g[I].valu',
     'r(let O of k)g[O].valu'),
    # 485 rename
    ('&&(F?(it(I,"arm"),it(I,"begi',
     '&&(F?(ot(O,"arm"),ot(O,"begi'),
    # 486 rename
    (')):N&&it(I,"arm"',
     ')):N&&ot(O,"arm"'),
    # 487 rename
    ('zt(Tr,Bt,ot),zt(Dr,jt,C);for(',
     'zt(Tr,Kt,it),zt(Ar,jt,D);for('),
    # 488 rename
    ('ue;let F=nt(Q,{type:"read',
     'ue;let F=nt(J,{type:"read'),
    # 489 rename
    ('ed});F.ok&&(Q=F.settings)',
     'ed});F.ok&&(J=F.settings)'),
    # 490 rename
    (' k=nt(Q,{type',
     ' k=nt(J,{type'),
    # 491 rename
    ('.ok&&(Q=k.set',
     '.ok&&(J=k.set'),
    # 492 rename
    ('gs,Yt=Q.field',
     'gs,Yt=J.field'),
    # 493 rename
    ('[k],F=Q.fields[k],I=J[k];re',
     '[k],F=J.fields[k],O=Q[k];re'),
    # 494 rename
    ('ull?{path:k,label:I.label,unit:I.unit,known:!0,val',
     'ull?{path:k,label:O.label,unit:O.unit,known:!0,val'),
    # 495 rename
    ('rom "+I.min+" to "+I.max+"',
     'rom "+O.min+" to "+O.max+"'),
    # 496 rename
    ('."}:{path:k,label:I.label,unit:I.unit,known:N.valu',
     '."}:{path:k,label:O.label,unit:O.unit,known:N.valu'),
    # 497 rename
    ('ll}}),Be=[],X',
     'll}}),Ke=[],X'),
    # 498 rename
    ('ue;if(Bt||ot){let',
     'ue;if(Kt||it){let'),
    # 499 rename
    ('||be===null?Be.push("The ',
     '||be===null?Ke.push("The '),
    # 500 rename
    ('f(jt||C){let ',
     'f(jt||D){let '),
    # 501 rename
    ('Soc"),Jt=N("e',
     'Soc"),Qt=N("e'),
    # 502 rename
    ('null||Jt===null?Be.push',
     'null||Qt===null?Ke.push'),
    # 503 rename
    ('onMin:Jt,targ',
     'onMin:Qt,targ'),
    # 504 rename
    ('=null,I=s?Ga(s):null;I&&(j(n,I.fpAct',
     '=null,O=s?Ba(s):null;O&&(j(n,O.fpAct'),
    # 505 rename
    ('||j(n,I.fpOp)||j(n,I.fpSna',
     '||j(n,O.fpOp)||j(n,O.fpSna'),
    # 506 rename
    ('ot))||ot||r&&',
     'ot))||it||r&&'),
    # 507 rename
    ('wer":(I&&(j(n,I.dgAct',
     'wer":(O&&(j(n,O.dgAct'),
    # 508 rename
    ('||j(n,I.dgOp)||j(n,I.dgSna',
     '||j(n,O.dgOp)||j(n,O.dgSna'),
    # 509 rename
    ('ot))||C||o&&(j(n,o.opera',
     'ot))||D||i&&(j(n,i.opera'),
    # 510 rename
    ('||j(n,o.snaps',
     '||j(n,i.snaps'),
    # 511 rename
    (');let Qt=t.co',
     ');let Jt=t.co'),
    # 512 rename
    ('":!1;!Qt&&k.s',
     '":!1;!Jt&&k.s'),
    # 513 rename
    ('rt")&&Be.push',
     'rt")&&Ke.push'),
    # 514 rename
    ('cked:!Qt})}let Ar=za(er({',
     'cked:!Jt})}let Cr=Ya(er({'),
    # 515 rename
    ('tings:Q}),qt,',
     'tings:J}),qt,'),
    # 516 rename
    ('tings:Q,field',
     'tings:J,field'),
    # 517 rename
    ('orrow:Ar,tou:',
     'orrow:Cr,tou:'),
    # 518 rename
    ('notes:Be},ove',
     'notes:Ke},ove'),
    # 519 rename
    ('ction za(e,n,',
     'ction Ya(e,n,'),
    # 520 rename
    ('Pct"),o=a!==v',
     'Pct"),i=a!==v'),
    # 521 rename
    ('oid 0,i=e.why',
     'oid 0,o=e.why'),
    # 522 rename
    ('e ")&&o?{...c',
     'e ")&&i?{...c'),
    # 523 rename
    ('argetSoc")||i.push({origi',
     'argetSoc")||o.push({origi'),
    # 524 rename
    ('.stopSoc")||i.push({origi',
     '.stopSoc")||o.push({origi'),
    # 525 rename
    ('ct")||i.push(',
     'ct")||o.push('),
    # 526 rename
    ('nown&&o?{...e',
     'nown&&i?{...e'),
    # 527 rename
    ('e,why:i,impor',
     'e,why:o,impor'),
    # 528 rename
    ('}}var U={conf',
     '}}var V={conf'),
    # 529 rename
    ('och"},Ya=/^(\\',
     'och"},qa=/^(\\'),
    # 530 rename
    ('))?$/,qa=/^(\\',
     '))?$/,Xa=/^(\\'),
    # 531 rename
    ('ction Xa(e){i',
     'ction Ja(e){i'),
    # 532 rename
    ('let n=Ya.exec',
     'let n=qa.exec'),
    # 533 rename
    ('ction or(e,n,',
     'ction ir(e,n,'),
    # 534 rename
    ('let a=qa.exec',
     'let a=Xa.exec'),
    # 535 rename
    ('};let o=e[n]?',
     '};let i=e[n]?'),
    # 536 rename
    ('ypeof o!="num',
     'ypeof i!="num'),
    # 537 rename
    ('inite(o)?{ok:',
     'inite(i)?{ok:'),
    # 538 rename
    ('round(o/60),t',
     'round(i/60),t'),
    # 539 rename
    ('}}var ir=4102',
     '}}var or=4102'),
    # 540 rename
    ('44800,Ja="Hel',
     '44800,Za="Hel'),
    # 541 rename
    ('two.",Za="A re',
     'two.",ei="A re'),
    # 542 rename
    (' it.",eo="This',
     ' it.",ti="This'),
    # 543 rename
    ('ction to(e){le',
     'ction ni(e){le'),
    # 544 rename
    ('6097),o=r-a*146097,i=Math.',
     '6097),i=r-a*146097,o=Math.'),
    # 545 rename
    ('loor((o-Math.floor(o/1460)',
     'loor((i-Math.floor(i/1460)'),
    # 546 rename
    ('floor(o/36524',
     'floor(i/36524'),
    # 547 rename
    ('floor(o/14609',
     'floor(i/14609'),
    # 548 rename
    ('65),s=o-(365*i+Math.floor(i/4)-Ma',
     '65),s=i-(365*o+Math.floor(o/4)-Ma'),
    # 549 rename
    ('floor(i/100))',
     'floor(o/100))'),
    # 550 rename
    ('l-9,p=i+a*400',
     'l-9,p=o+a*400'),
    # 551 rename
    ('ction no(e,n,t',
     'ction ri(e,n,t'),
    # 552 rename
    ('<0||r>ir)retu',
     '<0||r>or)retu'),
    # 553 rename
    ('and "+ir+" se',
     'and "+or+" se'),
    # 554 rename
    (',text:to(a)+" ',
     ',text:ni(a)+" '),
    # 555 rename
    ('ction ro(e,n,t',
     'ction ai(e,n,t'),
    # 556 rename
    ('ction ao(e,n,t',
     'ction ii(e,n,t'),
    # 557 rename
    ('};let o=[];for(let i of le',
     '};let i=[];for(let o of le'),
    # 558 rename
    ('t s=X[i],l=U[i+"_sta',
     't s=X[o],l=V[o+"_sta'),
    # 559 rename
    ('t"],c=U[i+"_exp',
     't"],c=V[o+"_exp'),
    # 560 rename
    ('s"],d=U[i+"_exp',
     's"],d=V[o+"_exp'),
    # 561 rename
    ('h"],p=or(e,c,',
     'h"],p=ir(e,c,'),
    # 562 rename
    ('y"),v=no(e,d,s',
     'y"),v=ri(e,d,s'),
    # 563 rename
    ('"in v?o.push(',
     '"in v?i.push('),
    # 564 rename
    ('let b=ro(p,v,n',
     'let b=ai(p,v,n'),
    # 565 rename
    ('ndMin,R=or(e,l,',
     'ndMin,P=ir(e,l,'),
    # 566 rename
    (');if(!R.ok)t.push(R.reaso',
     ');if(!P.ok)t.push(P.reaso'),
    # 567 rename
    ('t x=_-R.min;i',
     't x=_-P.min;i'),
    # 568 rename
    ('(x>ce[i])t.pu',
     '(x>ce[o])t.pu'),
    # 569 rename
    ('e{let C={kind:i,start',
     'e{let D={kind:o,start'),
    # 570 rename
    ('AtMin:R.min,e',
     'AtMin:P.min,e'),
    # 571 rename
    ('in:_},P=!0;if(i==="pr',
     'in:_},R=!0;if(o==="pr'),
    # 572 rename
    ('W=M(e,U.prepa',
     'W=M(e,V.prepa'),
    # 573 rename
    ('W)||W<m.reser',
     'W)||W<h.reser'),
    # 574 rename
    ('in||W>m.reser',
     'in||W>h.reser'),
    # 575 rename
    ('ide "+m.reserveMin+"-"+m.reserveMax+',
     'ide "+h.reserveMin+"-"+h.reserveMax+'),
    # 576 rename
    ('ed."),P=!1):C.reser',
     'ed."),R=!1):D.reser'),
    # 577 rename
    ('Pct=W}P&&(E={',
     'Pct=W}R&&(E={'),
    # 578 rename
    ('rride:C,label',
     'rride:D,label'),
    # 579 rename
    ('poch"?Ja:""})',
     'poch"?Za:""})'),
    # 580 rename
    ('{kind:i,label',
     '{kind:o,label'),
    # 581 rename
    ('tive"?eo:b.rea',
     'tive"?ti:b.rea'),
    # 582 rename
    ('able"?Za:"",ep',
     'able"?ei:"",ep'),
    # 583 rename
    ('eturn o.lengt',
     'eturn i.lengt'),
    # 584 rename
    (' of "+o.join(',
     ' of "+i.join('),
    # 585 rename
    ('so "+(o.lengt',
     'so "+(i.lengt'),
    # 586 rename
    ('tion oo(e){le',
     'tion oi(e){le'),
    # 587 rename
    ('n=M(e,U.revis',
     'n=M(e,V.revis'),
    # 588 rename
    ('ction io(e,n,t',
     'ction si(e,n,t'),
    # 589 rename
    ('alues(U),o=a.fil',
     'alues(V),i=a.fil'),
    # 590 rename
    ('0);if(o.lengt',
     '0);if(i.lengt'),
    # 591 rename
    ('l;let i=Qa(e,U.confi',
     'l;let o=Qa(e,V.confi'),
    # 592 rename
    ('irmed:i,minEx',
     'irmed:o,minEx'),
    # 593 rename
    ('n:M(e,U.min_e',
     'n:M(e,V.min_e'),
    # 594 rename
    ('aultMin:M(e,U.hold_defaul',
     'aultMin:M(e,V.hold_defaul'),
    # 595 rename
    ('dCapMin:M(e,U.hold_cap),s',
     'dCapMin:M(e,V.hold_cap),s'),
    # 596 rename
    ('ilMin:Xa(G(e,U.skip_',
     'ilMin:Ja(G(e,V.skip_'),
    # 597 rename
    ('n:M(e,U.skip_',
     'n:M(e,V.skip_'),
    # 598 rename
    ('n:M(e,U.cut_d',
     'n:M(e,V.cut_d'),
    # 599 rename
    ('n:M(e,U.cut_c',
     'n:M(e,V.cut_c'),
    # 600 rename
    ('t:M(e,U.cut_r',
     't:M(e,V.cut_r'),
    # 601 rename
    ('ds:v}=ao(e,n,d',
     'ds:v}=ii(e,n,d'),
    # 602 rename
    ('ssing:o,confirmed:i,polic',
     'ssing:i,confirmed:o,polic'),
    # 603 rename
    ('sion:oo(e),ac',
     'sion:oi(e),ac'),
    # 604 rename
    ('Pct"),o=e.pla',
     'Pct"),i=e.pla'),
    # 605 rename
    ('y_soc,i=o?M(n,o):null,s=io(n,t,a',
     'y_soc,o=i?M(n,i):null,s=si(n,t,a'),
    # 606 rename
    (':null,i);retu',
     ':null,o);retu'),
    # 607 rename
    ('."}}),so="SHAD',
     '."}}),li="SHAD'),
    # 608 rename
    ('ing.",lo="Quic',
     'ing.",ci="Quic'),
    # 609 rename
    ('yet.",co="Quic',
     'yet.",di="Quic'),
    # 610 rename
    ('ve.",uo="Stat',
     've.",ui="Stat'),
    # 611 rename
    ('on.",po="This',
     'on.",pi="This'),
    # 612 rename
    ('ction Ut(e,n)',
     'ction Vt(e,n)'),
    # 613 rename
    ('"}var ho={HIGH',
     '"}var mi={HIGH'),
    # 614 rename
    ('ction Vt(e){r',
     'ction Ut(e){r'),
    # 615 rename
    ('urn`${B(e.sta',
     'urn`${K(e.sta'),
    # 616 rename
    ('`}var mo=e=>"t',
     '`}var hi=e=>"t'),
    # 617 rename
    ('me"in J[e.pat',
     'me"in Q[e.pat'),
    # 618 rename
    ('eturn mo(e)?B(n):e.',
     'eturn hi(e)?K(n):e.'),
    # 619 rename
    ('tion fo(e){if',
     'tion fi(e){if'),
    # 620 rename
    (',chip:Vt(e.st',
     ',chip:Ut(e.st'),
    # 621 rename
    ('tion go(e){le',
     'tion gi(e){le'),
    # 622 rename
    ('art ${B(n.sta',
     'art ${K(n.sta'),
    # 623 rename
    ('ed, ${B(t.sta',
     'ed, ${K(t.sta'),
    # 624 rename
    ('}var bo={"nat',
     '}var bi={"nat'),
    # 625 rename
    ('an"},vo={OK:"',
     'an"},vi={OK:"'),
    # 626 rename
    ('tion _o(e){le',
     'tion _i(e){le'),
    # 627 rename
    ('TCH"?go(s):nu',
     'TCH"?gi(s):nu'),
    # 628 rename
    ('xt:`${B(s.int',
     'xt:`${K(s.int'),
    # 629 rename
    (' to ${B(c.int',
     ' to ${K(c.int'),
    # 630 rename
    ('anMin:K(s.int',
     'anMin:B(s.int'),
    # 631 rename
    ('Text:bo[s.ori',
     'Text:bi[s.ori'),
    # 632 rename
    ('ength,o=[...n',
     'ength,i=[...n'),
    # 633 rename
    ('es])],i;retur',
     'es])],o;retur'),
    # 634 rename
    ('lback?i="No a',
     'lback?o="No a'),
    # 635 rename
    ('="OK"?i=`If t',
     '="OK"?o=`If t'),
    # 636 rename
    ('IBLE"?i="The ',
     'IBLE"?o="The '),
    # 637 rename
    ('LICT"?i="The ',
     'LICT"?o="The '),
    # 638 rename
    ('wed.":i="The ',
     'wed.":o="The '),
    # 639 rename
    ('dline:i,statu',
     'dline:o,statu'),
    # 640 rename
    ('Text:vo[t.sta',
     'Text:vi[t.sta'),
    # 641 rename
    ('asons:o,slots',
     'asons:i,slots'),
    # 642 rename
    ('}var wo={hold',
     '}var wi={hold'),
    # 643 rename
    ('tion xo(){let',
     'tion xi(){let'),
    # 644 rename
    ('lMin"?B(r):t=',
     'lMin"?K(r):t='),
    # 645 rename
    ('til ${B(e.ski',
     'til ${K(e.ski'),
    # 646 rename
    ('tion yo(e){re',
     'tion yi(e){re'),
    # 647 rename
    ('tion So(e){le',
     'tion Si(e){le'),
    # 648 rename
    ('e.map(o=>({kind:o.overr',
     'e.map(i=>({kind:i.overr'),
    # 649 rename
    ('.kind,label:o.label,until',
     '.kind,label:i.label,until'),
    # 650 rename
    ('til ${o.expir',
     'til ${i.expir'),
    # 651 rename
    ('n ${Z(o.remai',
     'n ${Z(i.remai'),
    # 652 rename
    ('Text:wo[o.overr',
     'Text:wi[i.overr'),
    # 653 rename
    ('kind](o.overr',
     'kind](i.overr'),
    # 654 rename
    ('serve:o.overr',
     'serve:i.overr'),
    # 655 rename
    ('ypeof o.overr',
     'ypeof i.overr'),
    # 656 rename
    ('ocPct<o.overr',
     'ocPct<i.overr'),
    # 657 rename
    ('vePct?Ut(e.socPct,o.overr',
     'vePct?Vt(e.socPct,i.overr'),
    # 658 rename
    ('):null,note:o.note})),a=e',
     '):null,note:i.note})),a=e'),
    # 659 rename
    ('t?[]:xo(),rev',
     't?[]:xi(),rev'),
    # 660 rename
    ('d.map(o=>({kind:o.kind,label:o.label',
     'd.map(i=>({kind:i.kind,label:i.label'),
    # 661 rename
    ('xt:Ht(o,e.nowMin),note:o.note})),pro',
     'xt:Ht(i,e.nowMin),note:i.note})),pro'),
    # 662 rename
    ('note:uo,recor',
     'note:ui,recor'),
    # 663 rename
    ('Note:po}}func',
     'Note:pi}}func'),
    # 664 rename
    ('ow,r=(o,i,s,l)=',
     'ow,r=(i,o,s,l)='),
    # 665 rename
    ('?{key:o,label:i,known',
     '?{key:i,label:o,known'),
    # 666 rename
    (',chip:Vt(s.st',
     ',chip:Ut(s.st'),
    # 667 rename
    (':{key:o,label:i,known',
     ':{key:i,label:o,known'),
    # 668 rename
    ('shMin,o=>B(o)),r("',
     'shMin,i=>K(i)),r("'),
    # 669 rename
    ('vePct,o=>`${o} %`)]',
     'vePct,i=>`${i} %`)]'),
    # 670 rename
    (',text:ho[t.con',
     ',text:mi[t.con'),
    # 671 rename
    (',chip:Vt(t.co',
     ',chip:Ut(t.co'),
    # 672 rename
    ('sLine:so,advic',
     'sLine:li,advic'),
    # 673 rename
    ('y.map(o=>({origin:o.origi',
     'y.map(i=>({origin:i.origi'),
    # 674 rename
    (',text:o.text}',
     ',text:i.text}'),
    # 675 rename
    ('.map(fo),tou:_o(e),ov',
     '.map(fi),tou:_i(e),ov'),
    # 676 rename
    ('h===0?co:`Quic',
     'h===0?di:`Quic'),
    # 677 rename
    ('s.map(o=>X[o.kind]',
     's.map(i=>X[i.kind]'),
    # 678 rename
    (').`)+yo(n):e.',
     ').`)+yi(n):e.'),
    # 679 rename
    ('h===0?lo:`Quic',
     'h===0?ci:`Quic'),
    # 680 rename
    ('s.map(o=>o.kind)',
     's.map(i=>i.kind)'),
    # 681 rename
    ('ck:n?So(n):nu',
     'ck:n?Si(n):nu'),
    # 682 rename
    ('ction hr(e){l',
     'ction mr(e){l'),
    # 683 rename
    ('dline,o=null,i=!1;if',
     'dline,i=null,o=!1;if'),
    # 684 rename
    (',"")),o=s.joi',
     ',"")),i=s.joi'),
    # 685 rename
    ('B7 "),i=!r.po',
     'B7 "),o=!r.po'),
    # 686 rename
    ('imits:o,limit',
     'imits:i,limit'),
    # 687 rename
    ('ntion:i}}func',
     'ntion:o}}func'),
    # 688 rename
    ('ction mr(e){r',
     'ction hr(e){r'),
    # 689 rename
    ('te}</span>`:h}\n        ${',
     'te}</span>`:m}\n        ${'),
    # 690 rename
    ('known?h:u`<sp',
     'known?m:u`<sp'),
    # 691 rename
    ('tion Eo(e){re',
     'tion Ei(e){re'),
    # 692 rename
    ('te}</span>`:h}\n      ${e.',
     'te}</span>`:m}\n      ${e.'),
    # 693 rename
    ('ve}</span>`:h}\n    </li>\n',
     've}</span>`:m}\n    </li>\n'),
    # 694 rename
    ('tion ko(e){re',
     'tion ki(e){re'),
    # 695 rename
    ('.map(Eo)}</ul>`:h}${e.h',
     '.map(Ei)}</ul>`:m}${e.h'),
    # 696 rename
    ('.map(ko)}</ul>`:h}${n&&',
     '.map(ki)}</ul>`:m}${n&&'),
    # 697 rename
    ('sNote}</p>`:h}\n      <p c',
     'sNote}</p>`:m}\n      <p c'),
    # 698 rename
    ('{t}</li>`)}</ul>`:h}\n      ${e.warnin',
     '{t}</li>`)}</ul>`:m}\n      ${e.warnin'),
    # 699 rename
    ('{t}</li>`)}</ul>`:h}\n      ${e.proble',
     '{t}</li>`)}</ul>`:m}\n      ${e.proble'),
    # 700 rename
    ('{t}</li>`)}</ul>`:h}\n      ${e.missin',
     '{t}</li>`)}</ul>`:m}\n      ${e.missin'),
    # 701 rename
    (', ")}.</p>`:h}\n      ${e.',
     ', ")}.</p>`:m}\n      ${e.'),
    # 702 rename
    ('          `:h}\n      <p c',
     '          `:m}\n      <p c'),
    # 703 rename
    ('p>${n?h:u`\n  ',
     'p>${n?m:u`\n  '),
    # 704 rename
    ('/span></p>`:h}\n    </li>\n',
     '/span></p>`:m}\n    </li>\n'),
    # 705 rename
    ('tion Mo(e,n,t',
     'tion Mi(e,n,t'),
    # 706 rename
    ('eNote}</p>`:h}\n          ',
     'eNote}</p>`:m}\n          '),
    # 707 rename
    ('ap(a=>mr(a.ke',
     'ap(a=>hr(a.ke'),
    # 708 rename
    ('ils>`:h}${n}\n',
     'ils>`:m}${n}\n'),
    # 709 rename
    ('xt}</span>`:h}</h3><span ',
     'xt}</span>`:m}</h3><span '),
    # 710 rename
    ('i>`)}</ul>`:h}\n          ',
     'i>`)}</ul>`:m}\n          '),
    # 711 rename
    ('          `:h}\n        </',
     '          `:m}\n        </'),
    # 712 rename
    ('ction Ro(e,n,t',
     'ction Pi(e,n,t'),
    # 713 rename
    ('eNote}</p>`:h}\n        <d',
     'eNote}</p>`:m}\n        <d'),
    # 714 rename
    ('s.map(mr)}</d',
     's.map(hr)}</d'),
    # 715 rename
    ('y.map(o=>u`<l',
     'y.map(i=>u`<l'),
    # 716 rename
    ('gin=${o.origin}>${o.text}',
     'gin=${i.origin}>${i.text}'),
    # 717 rename
    ('lock):h}${n}\n',
     'lock):m}${n}\n'),
    # 718 rename
    ('xt}</span>`:h}</h3>\n     ',
     'xt}</span>`:m}</h3>\n     '),
    # 719 rename
    ('s.map(o=>u`<li>${o}</li>`)}</ul>`:h}\n        ${',
     's.map(i=>u`<li>${i}</li>`)}</ul>`:m}\n        ${'),
    # 720 rename
    ('s.map(o=>u`<s',
     's.map(i=>u`<s'),
    # 721 rename
    ('seg ${o.misma',
     'seg ${i.misma'),
    # 722 rename
    ('row:"+o.spanMin}>${o.index',
     'row:"+i.spanMin}>${i.index'),
    # 723 rename
    ('          `:h}\n      </di',
     '          `:m}\n      </di'),
    # 724 rename
    ('ction Po(e,n=h){retu',
     'ction Ri(e,n=m){retu'),
    # 725 rename
    ('n n!==h?u`\n  ',
     'n n!==m?u`\n  '),
    # 726 rename
    ('s">${Mo(e,n,hr(e))}',
     's">${Mi(e,n,mr(e))}'),
    # 727 rename
    ('ly">${Ro(e,h,!1)}<',
     'ly">${Pi(e,m,!1)}<'),
    # 728 rename
    ('eturn h;let a',
     'eturn m;let a'),
    # 729 rename
    ('now(),o=sr(e,',
     'now(),i=sr(e,'),
    # 730 rename
    ('6e4)),i=pr(o),s=e.',
     '6e4)),o=pr(i),s=e.'),
    # 731 rename
    ('eturn Po(i,r?r({snap:o,state',
     'eturn Ri(o,r?r({snap:i,state'),
    # 732 rename
    ('ull}):h)}var ',
     'ull}):m)}var '),
    # 733 rename
    ('ction Kt(e,n,',
     'ction Bt(e,n,'),
    # 734 rename
    ('.some(i=>i!=="en',
     '.some(o=>o!=="en'),
    # 735 rename
    ('_id"&&i!=="va',
     '_id"&&o!=="va'),
    # 736 rename
    ('ty_id,o=typeo',
     'ty_id,i=typeo'),
    # 737 rename
    ('ipt&&!o?!1:r.',
     'ipt&&!i?!1:r.'),
    # 738 rename
    ('null||o?!1:Ob',
     'null||i?!1:Ob'),
    # 739 rename
    ('every(i=>i==="kind"||i==="ex',
     'every(o=>o==="kind"||o==="ex'),
    # 740 rename
    ('min"||i==="un',
     'min"||o==="un'),
    # 741 rename
    ('cal"||i==="ex',
     'cal"||o==="ex'),
    # 742 rename
    ('}var To=["NOT',
     '}var Ti=["NOT'),
    # 743 rename
    ('IND"],Do=" Hom',
     'IND"],Ai=" Hom'),
    # 744 rename
    ('.find(o=>o===r.k',
     '.find(i=>i===r.k'),
    # 745 rename
    ('ction Ao(e,n,t,r,a,o){if(!',
     'ction Ci(e,n,t,r,a,i){if(!'),
    # 746 rename
    ('l;let i=t.rev',
     'l;let o=t.rev'),
    # 747 rename
    ('on;if(i!==nul',
     'on;if(o!==nul'),
    # 748 rename
    ('ll&&r>i+1)ret',
     'll&&r>o+1)ret'),
    # 749 rename
    ('let s=i!==nul',
     'let s=o!==nul'),
    # 750 rename
    ('ll&&r>i,l=a!=',
     'll&&r>o,l=a!='),
    # 751 rename
    ('ull&&To.some(',
     'ull&&Ti.some('),
    # 752 rename
    ('"};if(o===voi',
     '"};if(i===voi'),
    # 753 rename
    ('let p=o.read=',
     'let p=i.read='),
    # 754 rename
    ('ed",v=o.epoch',
     'ed",v=i.epoch'),
    # 755 rename
    ('": "+(o.epoch',
     '": "+(i.epoch'),
    # 756 rename
    ('let b=o.read=',
     'let b=i.read='),
    # 757 rename
    ('il "+(o.endTe',
     'il "+(i.endTe'),
    # 758 rename
    ('g+"."+Do}}var Ke={eff',
     'g+"."+Ai}}var Be={eff'),
    # 759 rename
    ('ction Co(e,n){',
     'ction Di(e,n){'),
    # 760 rename
    ('ript),o=t(U.confirmed),i=t(Ke.effe',
     'ript),i=t(V.confirmed),o=t(Be.effe'),
    # 761 rename
    ('),s=t(Ke.expo',
     '),s=t(Be.expo'),
    # 762 rename
    ('ript),o||d.push(U.confirmed),i||d.push(Ke.effe',
     'ript),i||d.push(V.confirmed),o||d.push(Be.effe'),
    # 763 rename
    ('.push(Ke.expo',
     '.push(Be.expo'),
    # 764 rename
    ('witch:o,effec',
     'witch:i,effec'),
    # 765 rename
    ('serve:i,expor',
     'serve:o,expor'),
    # 766 rename
    ('}var No="Over',
     '}var Ni="Over'),
    # 767 rename
    ('ady.",Io="Over',
     'ady.",Oi="Over'),
    # 768 rename
    ('ady.",Oo="Turn',
     'ady.",Ii="Turn'),
    # 769 rename
    ('tion $o(e,n,t',
     'tion $i(e,n,t'),
    # 770 rename
    (',text:Oo};if(n',
     ',text:Ii};if(n'),
    # 771 rename
    (',text:Io+" Not',
     ',text:Oi+" Not'),
    # 772 rename
    ('text:No}}function Lo(e){let n=Ke.effe',
     'text:Ni}}function Li(e){let n=Be.effe'),
    # 773 rename
    ('tion Wo(e,n,t',
     'tion Wi(e,n,t'),
    # 774 rename
    ('){let o=e!==n',
     '){let i=e!==n'),
    # 775 rename
    (':null,i=a!==n',
     ':null,o=a!==n'),
    # 776 rename
    ('=null?i+" "+e+" %":i+" unk',
     '=null?o+" "+e+" %":o+" unk'),
    # 777 rename
    ('Raise:o}}func',
     'Raise:i}}func'),
    # 778 rename
    ('id 0),o=e.sna',
     'id 0),i=e.sna'),
    # 779 rename
    ('Pct"),i=o&&o.known?o.value',
     'Pct"),o=i&&i.known?i.value'),
    # 780 rename
    ('ull,l=Co(e.sta',
     'ull,l=Di(e.sta'),
    # 781 rename
    ('t),c=$o(l,n.c',
     't),c=$i(l,n.c'),
    # 782 rename
    ('ve,p=Lo(e.sta',
     've,p=Li(e.sta'),
    # 783 rename
    ('own&&(i===nul',
     'own&&(o===nul'),
    # 784 rename
    ('lue!==i),b=Wo(i,d?d.r',
     'lue!==o),b=Wi(o,d?d.r'),
    # 785 rename
    ('>{let R=n.act',
     '>{let P=n.act'),
    # 786 rename
    (',x=[],C=null;if(!s)C=n.sta',
     ',x=[],D=null;if(!s)D=n.sta'),
    # 787 rename
    ('let w=Qn(_,s,',
     'let w=Jn(_,s,'),
    # 788 rename
    ('lock),D=w.len',
     'lock),A=w.len'),
    # 789 rename
    ('ull,$=Jn(_,t,D?D.expir',
     'ull,$=Qn(_,t,A?A.expir'),
    # 790 rename
    ('vePct:i});if(',
     'vePct:o});if('),
    # 791 rename
    ('ENT"))C=$.err',
     'ENT"))D=$.err'),
    # 792 rename
    ('il(T);C="The ',
     'il(T);D="The '),
    # 793 rename
    ('h===0?C="No l',
     'h===0?D="No l'),
    # 794 rename
    ('=null?Kt(_,{u',
     '=null?Bt(_,{u'),
    # 795 rename
    ('0},r):Kt(_,{e',
     '0},r):Bt(_,{e'),
    # 796 rename
    (')}let P=n.hel',
     ')}let R=n.hel'),
    # 797 rename
    ('ull,W=R||null',
     'ull,W=P||null'),
    # 798 rename
    ('vePct?Ut(n.so',
     'vePct?Vt(n.so'),
    # 799 rename
    ('ctive:R!==nul',
     'ctive:P!==nul'),
    # 800 rename
    ('eText:R?"Acti',
     'eText:P?"Acti'),
    # 801 rename
    ('til "+R.expir',
     'til "+P.expir'),
    # 802 rename
    ('n "+Z(R.remai',
     'n "+Z(P.remai'),
    # 803 rename
    (')+")":P?Ht(P,t):nu',
     ')+")":R?Ht(R,t):nu'),
    # 804 rename
    (',held:P!==nul',
     ',held:R!==nul'),
    # 805 rename
    ('note:(R?R.note:P?P.note:',
     'note:(P?P.note:R?R.note:'),
    # 806 rename
    ('dback:Ao(_,X[_',
     'dback:Ci(_,X[_'),
    # 807 rename
    ('eason:C,cancel:R||P?wr(_,',
     'eason:D,cancel:P||R?wr(_,'),
    # 808 rename
    ('tion Fo(e,n){',
     'tion Fi(e,n){'),
    # 809 rename
    ('=n(e),o=a-n(e',
     '=n(e),i=a-n(e'),
    # 810 rename
    ('5);if(o===0)r',
     '5);if(i===0)r'),
    # 811 rename
    ('}};if(o!==60&&o!==-60',
     '}};if(i!==60&&i!==-60'),
    # 812 rename
    ('l;let i=e,s=e',
     'l;let o=e,s=e'),
    # 813 rename
    ('or(;s-i>6e4;)',
     'or(;s-o>6e4;)'),
    # 814 rename
    ('loor((i+s)/2)',
     'loor((o+s)/2)'),
    # 815 rename
    (')===a?i=c:s=c',
     ')===a?o=c:s=c'),
    # 816 rename
    ('taMin:o}}}fun',
     'taMin:i}}}fun'),
    # 817 rename
    ('turn Fo(e,n=>',
     'turn Fi(e,n=>'),
    # 818 rename
    (')}var Vo={hold',
     ')}var Ui={hold'),
    # 819 rename
    ('ry."},Uo={hold',
     'ry."},Vi={hold'),
    # 820 rename
    ('s."},Ho="Part',
     's."},Hi="Part'),
    # 821 rename
    ('tion Go(e,n){',
     'tion Gi(e,n){'),
    # 822 rename
    ('tiveText}</span>`:h}\n      </div>\n   ',
     'tiveText}</span>`:m}\n      </div>\n   '),
    # 823 rename
    ('ect>${Uo[e.kin',
     'ect>${Vi[e.kin'),
    # 824 rename
    ('pan>`:h} &mid',
     'pan>`:m} &mid'),
    # 825 rename
    ('/span></p>`:h}\n      ${e.',
     '/span></p>`:m}\n      ${e.'),
    # 826 rename
    ('.note}</p>`:h}\n      ${e.',
     '.note}</p>`:m}\n      ${e.'),
    # 827 rename
    ('serve}</p>`:h}\n      ${e.',
     'serve}</p>`:m}\n      ${e.'),
    # 828 rename
    ('eason}</p>`:h}\n      <div',
     'eason}</p>`:m}\n      <div'),
    # 829 rename
    ('r"}</span>`:h}\n        ${',
     'r"}</span>`:m}\n        ${'),
    # 830 rename
    ('ton>`:h}\n    ',
     'ton>`:m}\n    '),
    # 831 rename
    ('on">${Vo[e.kin',
     'on">${Ui[e.kin'),
    # 832 rename
    ('.text}</p>`:h}\n    </div>',
     '.text}</p>`:m}\n    </div>'),
    # 833 rename
    ('ction Ko(e,n){',
     'ction Bi(e,n){'),
    # 834 rename
    ('ess.text}</span>`:h}\n      </div>\n   ',
     'ess.text}</span>`:m}\n      </div>\n   '),
    # 835 rename
    ('e">${Ho}</p>\n',
     'e">${Hi}</p>\n'),
    # 836 rename
    ('p(t=>Go(t,n))',
     'p(t=>Gi(t,n))'),
    # 837 rename
    ('esult}</p>`:h}\n    </div>',
     'esult}</p>`:m}\n    </div>'),
    # 838 rename
    ('ction Rr(e){r',
     'ction Pr(e){r'),
    # 839 rename
    ('>{let o=Er({s',
     '>{let i=Er({s'),
    # 840 rename
    ('eturn o?Ko(o,i=>{Sr(Mr,i,o.lastR',
     'eturn i?Bi(i,o=>{Sr(Mr,o,i.lastR'),
    # 841 rename
    ('lt),e(i)}):h}}var Pr=de`\n',
     'lt),e(o)}):m}}var Rr=de`\n'),
    # 842 rename
    ('t=4e3,Bo=1e3,A=class',
     't=4e3,Ki=1e3,C=class'),
    # 843 rename
    ('void 0);let o=y(this._ent',
     'void 0);let i=y(this._ent'),
    # 844 rename
    ('ive)),i=y(thi',
     'ive)),o=y(thi'),
    # 845 rename
    ('ctive:o,armed:i,opera',
     'ctive:i,armed:o,opera'),
    # 846 rename
    (');let o=a.schedule;o&&(thi',
     ');let i=a.schedule;i&&(thi'),
    # 847 rename
    ('State(o.power',
     'State(i.power'),
    # 848 rename
    ('State(o.stop_',
     'State(i.stop_'),
    # 849 rename
    ('State(o.durat',
     'State(i.durat'),
    # 850 rename
    ('oid 0));let i=y(this._ent',
     'oid 0));let o=y(this._ent'),
    # 851 rename
    ('=et({active:i,armed:s,ope',
     '=et({active:o,armed:s,ope'),
    # 852 rename
    ('s.hass){let o=this._track',
     's.hass){let i=this._track'),
    # 853 rename
    ('();Tn(o.fp.state,o.dump.',
     '();Tn(i.fp.state,i.dump.'),
    # 854 rename
    ('ck=Et(o.fp.state,o.dump.',
     'ck=Et(i.fp.state,i.dump.'),
    # 855 rename
    ('ow()},Bo):!t&&',
     'ow()},Ki):!t&&'),
    # 856 rename
    (')),a=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),i=this.',
     ')),a=y(this._entityState(t.write_enable)),i=y(this._entityState(t.operation_in_progress)),o=this.'),
    # 857 rename
    ('gress:o,statusText:i})}_du',
     'gress:i,statusText:o})}_du'),
    # 858 rename
    ('r=y(this._entityState(t.active)),a=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),i=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status);re',
     'r=y(this._entityState(t.active)),a=y(this._entityState(t.write_enable)),i=y(this._entityState(t.operation_in_progress)),o=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status);re'),
    # 859 rename
    ('erationInProgress:o,snapshotValid:i,statusText:s})}_e',
     'erationInProgress:i,snapshotValid:o,statusText:s})}_e'),
    # 860 rename
    ('oid 0,Rr(t=>t',
     'oid 0,Pr(t=>t'),
    # 861 rename
    ('id 0},o=this.',
     'id 0},i=this.'),
    # 862 rename
    ('f(t!==null&&o){let l=this',
     'f(t!==null&&i){let l=this'),
    # 863 rename
    ('):t,d=Oe(t,r)',
     '):t,d=Ie(t,r)'),
    # 864 rename
    ('entityState(o.status)}}let i=this.',
     'entityState(i.status)}}let o=this.'),
    # 865 rename
    ('rid,s=i&&this',
     'rid,s=o&&this'),
    # 866 rename
    ('null&&i){let l=i.sched',
     'null&&o){let l=o.sched'),
    # 867 rename
    ('ll),d=Oe(r,t)',
     'll),d=Ie(r,t)'),
    # 868 rename
    ('entityState(i.status)}}re',
     'entityState(o.status)}}re'),
    # 869 rename
    ('tate),o=a==="',
     'tate),i=a==="'),
    # 870 rename
    ('ower",i=a==="',
     'ower",o=a==="'),
    # 871 rename
    ('.fp,s=An(Dn(i.state',
     '.fp,s=Cn(An(o.state'),
    # 872 rename
    ('>${Nn(Cn(o),i.label,i.statu',
     '>${Nn(Dn(i),o.label,o.statu'),
    # 873 rename
    ('Track(o)}>Sho',
     'Track(i)}>Sho'),
    # 874 rename
    ('          `:h}\n        <d',
     '          `:m}\n        <d'),
    # 875 rename
    (');let r=y(this._entityState(t.active)),a=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),i=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status),l=Ze({ac',
     ');let r=y(this._entityState(t.active)),a=y(this._entityState(t.write_enable)),i=y(this._entityState(t.operation_in_progress)),o=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status),l=Ze({ac'),
    # 876 rename
    ('erationInProgress:o,statusText:s});if',
     'erationInProgress:i,statusText:s});if'),
    # 877 rename
    ('k(),g=Oe(l,b)',
     'k(),g=Ie(l,b)'),
    # 878 rename
    ('oid 0,R=this.',
     'oid 0,P=this.'),
    # 879 rename
    ('ntity(t.duration),C=this._pendingPower??S(R?.state),P=this.',
     'ntity(t.duration),D=this._pendingPower??S(P?.state),R=this.'),
    # 880 rename
    ('ScheduleBanner(c):h}\n          ${g?th',
     'ScheduleBanner(c):m}\n          ${g?th'),
    # 881 rename
    ('er(_):h}\n\n   ',
     'er(_):m}\n\n   '),
    # 882 rename
    ('t:s,snapshotValid:i,interlocked:g,stagedPowerW:C,stagedDurat',
     't:s,snapshotValid:o,interlocked:g,stagedPowerW:D,stagedDurat'),
    # 883 rename
    ('onMin:P,stage',
     'onMin:R,stage'),
    # 884 rename
    ('PowerEntity:R,stagedDurat',
     'PowerEntity:P,stagedDurat'),
    # 885 rename
    ('!r.schedule,o=a?this._mod',
     '!r.schedule,i=a?this._mod'),
    # 886 rename
    ('derModeSelector():h}\n      ${o==="later"&&r.sche',
     'derModeSelector():m}\n      ${i==="later"&&r.sche'),
    # 887 rename
    ('rmed",o=$e(vn',
     'rmed",i=$e(vn'),
    # 888 rename
    ('cked),i=$e(_n',
     'cked),o=$e(_n'),
    # 889 rename
    ('ggle ${a?"is-armed":""}"\n          ?disabled=${!i}\n          @click=${()=>this._toggleArm(r.fp.wr',
     'ggle ${a?"is-armed":""}"\n          ?disabled=${!o}\n          @click=${()=>this._toggleArm(r.fp.wr'),
    # 890 rename
    ('tart-button"\n          ?disabled=${!o}\n          @click=${()=>this._callS',
     'tart-button"\n          ?disabled=${!i}\n          @click=${()=>this._callS'),
    # 891 rename
    ('erLaterPanel(t){let r=y(this._entityState(t.armed)),a=Pt(r),o=this._entityState(t.start),i=fe(o),s=this._entity(t.duration),l=this._entity(t.power),c',
     'erLaterPanel(t){let r=y(this._entityState(t.armed)),a=Rt(r),i=this._entityState(t.start),o=fe(i),s=this._entity(t.duration),l=this._entity(t.power),c'),
    # 892 rename
    ('e3),_=On(E,g),R=Mt(d),x=Rt(d),C=!a&&i!==null&&i.getTi',
     'e3),_=In(E,g),P=Mt(d),x=Pt(d),D=!a&&o!==null&&o.getTi'),
    # 893 rename
    ('abel>\n        <input\n          type="datetime-local"\n          class="schedule-datetime-input"\n          .value=${i?this._toDatetimeLocalValue(i):""}\n          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}\n          ?disabled=${a}\n          @change=${P=>this',
     'abel>\n        <input\n          type="datetime-local"\n          class="schedule-datetime-input"\n          .value=${o?this._toDatetimeLocalValue(o):""}\n          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}\n          ?disabled=${a}\n          @change=${R=>this'),
    # 894 rename
    ('start,P.targe',
     'start,R.targe'),
    # 895 rename
    ('l,onPreview:P=>this._pend',
     'l,onPreview:R=>this._pend'),
    # 896 rename
    ('Power=P,onCommit:P=>this',
     'Power=R,onCommit:R=>this'),
    # 897 rename
    ('ower",P,t.pow',
     'ower",R,t.pow'),
    # 898 rename
    ('s,onPreview:P=>this._pend',
     's,onPreview:R=>this._pend'),
    # 899 rename
    ('ation=P,onCommit:P=>this',
     'ation=R,onCommit:R=>this'),
    # 900 rename
    ('tion",P,t.dur',
     'tion",R,t.dur'),
    # 901 rename
    ('ote ${R||x?"is-warning":""}">${d}</p>`:h}\n\n      <div class="action-ro',
     'ote ${P||x?"is-warning":""}">${d}</p>`:m}\n\n      <div class="action-ro'),
    # 902 rename
    ('${a||!C}\n          @click=${()=>this._callServiceObj(Dt(t.armed))}\n        >\n          <ha-icon ',
     '${a||!D}\n          @click=${()=>this._callServiceObj(At(t.armed))}\n        >\n          <ha-icon '),
    # 903 rename
    ('fe(r),o=S(this._entityState(t.duration)),i=S(this._entityState(t.power))',
     'fe(r),i=S(this._entityState(t.duration)),o=S(this._entityState(t.power))'),
    # 904 rename
    (' ${ne(i)} \u2022 ${ge(o)}\n   ',
     ' ${ne(o)} \u2022 ${ge(i)}\n   '),
    # 905 rename
    ('         class="schedule-cancel-button"\n          @click=${()=>this._callServiceObj(At(t.cancel))}\n        >\n          Cancel\n        </button>\n      </div>\n    `}_toDat',
     '         class="schedule-cancel-button"\n          @click=${()=>this._callServiceObj(Ct(t.cancel))}\n        >\n          Cancel\n        </button>\n      </div>\n    `}_toDat'),
    # 906 rename
    ('ceObj(In(t,$n',
     'ceObj(On(t,$n'),
    # 907 rename
    ('s._callServiceObj(Ct(a,r))}_renderAct',
     's._callServiceObj(Dt(a,r))}_renderAct'),
    # 908 rename
    ('e(t.fp.ends_at),a=fe(r),o=a?Le(a.getTime(),this._',
     'e(t.fp.ends_at),a=fe(r),i=a?Le(a.getTime(),this._'),
    # 909 rename
    ('l;return u`\n      <div class="active-hero">\n        <div class="active-hero-time">${o??"--:--"}</div>\n        <div class="active-hero-label">time remaining</div>\n      <',
     'l;return u`\n      <div class="active-hero">\n        <div class="active-hero-time">${i??"--:--"}</div>\n        <div class="active-hero-label">time remaining</div>\n      <'),
    # 910 rename
    ('on")):h}\n    ',
     'on")):m}\n    '),
    # 911 rename
    (')||!t?h:u`\n  ',
     ')||!t?m:u`\n  '),
    # 912 rename
    ('own=${i=>{(i.key==',
     'own=${o=>{(o.key=='),
    # 913 rename
    ('ter"||i.key==',
     'ter"||o.key=='),
    # 914 rename
    (' ")&&(i.preve',
     ' ")&&(o.preve'),
    # 915 rename
    ('erDiagnosticsDetails(t){let r=[],a=(o,i)=>{let s=S(this._entityState(i));s!==null&&r.push({label:o,value:s.toString()})};return a("Sta',
     'erDiagnosticsDetails(t){let r=[],a=(i,o)=>{let s=S(this._entityState(o));s!==null&&r.push({label:i,value:s.toString()})};return a("Sta'),
    # 916 rename
    ('Restored OK",t.restore_successes),a("Failures",t.failures),r.length===0?h:u`\n      <details class="diagnostics-details">\n        <summary>Details</summary>\n        <div class="diagnostics-row">\n          ${r.map(o=>u`<span class="diagnostic-chip">${o.label}: ${o.value}</span>`)}\n        </div>\n      </details>\n    `}_renderEndRestor',
     'Restored OK",t.restore_successes),a("Failures",t.failures),r.length===0?m:u`\n      <details class="diagnostics-details">\n        <summary>Details</summary>\n        <div class="diagnostics-row">\n          ${r.map(i=>u`<span class="diagnostic-chip">${i.label}: ${i.value}</span>`)}\n        </div>\n      </details>\n    `}_renderEndRestor'),
    # 917 rename
    ('t,r,a,o){let i=this.',
     't,r,a,i){let o=this.'),
    # 918 rename
    ('""} ${i?"conf',
     '""} ${o?"conf'),
    # 919 rename
    ('disabled=${!o}\n        @c',
     'disabled=${!i}\n        @c'),
    # 920 rename
    ('reClick(t)}\n      >\n        <ha-icon icon="mdi:backup-restore"></ha-icon>\n        ${i?"Tap again to End & Restore":r}\n        ${i?u`<span class="confirm-progress" style="animation-duration:${at}ms"></span>`:h}\n      </button>\n    `}_handl',
     'reClick(t)}\n      >\n        <ha-icon icon="mdi:backup-restore"></ha-icon>\n        ${o?"Tap again to End & Restore":r}\n        ${o?u`<span class="confirm-progress" style="animation-duration:${at}ms"></span>`:m}\n      </button>\n    `}_handl'),
    # 921 rename
    ('kMin),o=t.max',
     'kMin),i=t.max'),
    # 922 rename
    ('kMax),i=this.',
     'kMax),o=this.'),
    # 923 rename
    ('ity,c=o>a?Mat',
     'ity,c=i>a?Mat'),
    # 924 rename
    ('s-a)/(o-a)*10',
     's-a)/(i-a)*10'),
    # 925 rename
    ('max=${o}\n    ',
     'max=${i}\n    '),
    # 926 rename
    ('tep=${i}\n    ',
     'tep=${o}\n    '),
    # 927 rename
    (');let r=y(this._entityState(t.active)),a=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),i=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status),l=et({ac',
     ');let r=y(this._entityState(t.active)),a=y(this._entityState(t.write_enable)),i=y(this._entityState(t.operation_in_progress)),o=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status),l=et({ac'),
    # 928 rename
    ('erationInProgress:o,snapshotValid:i,statusText:s});if',
     'erationInProgress:i,snapshotValid:o,statusText:s});if'),
    # 929 rename
    ('k(),b=Oe(l,v)',
     'k(),b=Ie(l,v)'),
    # 930 rename
    ('ower),R=this.',
     'ower),P=this.'),
    # 931 rename
    ('ntity(t.duration),C=this._pendingDump',
     'ntity(t.duration),D=this._pendingDump'),
    # 932 rename
    ('S(_?.state),P=this._pendi',
     'S(_?.state),R=this._pendi'),
    # 933 rename
    ('oc??S(R?.stat',
     'oc??S(P?.stat'),
    # 934 rename
    ('ScheduleBanner(c):h}\n          ${b?th',
     'ScheduleBanner(c):m}\n          ${b?th'),
    # 935 rename
    ('er(E):h}\n\n   ',
     'er(E):m}\n\n   '),
    # 936 rename
    ('t:s,snapshotValid:i,interlocked:b,stagedPowerW:C,stagedStopSoc:P,stage',
     't:s,snapshotValid:o,interlocked:b,stagedPowerW:D,stagedStopSoc:R,stage'),
    # 937 rename
    ('opSocEntity:R,stagedDurat',
     'opSocEntity:P,stagedDurat'),
    # 938 rename
    ('mp.schedule,o=a?this._dum',
     'mp.schedule,i=a?this._dum'),
    # 939 rename
    ('umpModeSelector():h}\n      ${o==="later"&&a?this',
     'umpModeSelector():m}\n      ${i==="later"&&a?this'),
    # 940 rename
    ('rmed",o=$e(xn',
     'rmed",i=$e(xn'),
    # 941 rename
    ('cked),i=$e(yn',
     'cked),o=$e(yn'),
    # 942 rename
    ('ggle ${a?"is-armed":""}"\n          ?disabled=${!i}\n          @click=${()=>this._toggleArm(r.dump.',
     'ggle ${a?"is-armed":""}"\n          ?disabled=${!o}\n          @click=${()=>this._toggleArm(r.dump.'),
    # 943 rename
    ('tart-button"\n          ?disabled=${!o}\n          @click=${()=>this._press',
     'tart-button"\n          ?disabled=${!i}\n          @click=${()=>this._press'),
    # 944 rename
    ('mpLaterPanel(t){let r=y(this._entityState(t.armed)),a=Pt(r),o=this._entityState(t.start),i=fe(o),s=this._entity(t.duration),l=this._entity(t.power),c',
     'mpLaterPanel(t){let r=y(this._entityState(t.armed)),a=Rt(r),i=this._entityState(t.start),o=fe(i),s=this._entity(t.duration),l=this._entity(t.power),c'),
    # 945 rename
    ('()),E=Rt(d),_',
     '()),E=Pt(d),_'),
    # 946 rename
    ('=null,R=_&&!a&&i!==null&&i.getTi',
     '=null,P=_&&!a&&o!==null&&o.getTi'),
    # 947 rename
    ('art</label>\n        <input\n          type="datetime-local"\n          class="schedule-datetime-input"\n          .value=${i?this._toDatetimeLocalValue(i):""}\n          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}\n          ?disabled=${a}\n          @change=${x=',
     'art</label>\n        <input\n          type="datetime-local"\n          class="schedule-datetime-input"\n          .value=${o?this._toDatetimeLocalValue(o):""}\n          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}\n          ?disabled=${a}\n          @change=${x='),
    # 948 rename
    ('  ${_?h:u`<p ',
     '  ${_?m:u`<p '),
    # 949 rename
    ('E?"is-warning":""}">${d}</p>`:h}\n\n      <div class="action-ro',
     'E?"is-warning":""}">${d}</p>`:m}\n\n      <div class="action-ro'),
    # 950 rename
    ('ed=${!R}\n          @click=${()=>this._callServiceObj(Dt(t.armed))}\n        >\n          <ha-icon ',
     'ed=${!P}\n          @click=${()=>this._callServiceObj(At(t.armed))}\n        >\n          <ha-icon '),
    # 951 rename
    ('his._entityState(t.duration)),o=S(this._entityState(t.power)),i=S(thi',
     'his._entityState(t.duration)),i=S(this._entityState(t.power)),o=S(thi'),
    # 952 rename
    (' ${ne(o)} \u2022 s',
     ' ${ne(i)} \u2022 s'),
    # 953 rename
    (' ${we(i)} \u2022 $',
     ' ${we(o)} \u2022 $'),
    # 954 rename
    ('         class="schedule-cancel-button"\n          @click=${()=>this._callServiceObj(At(t.cancel))}\n        >\n          Cancel\n        </button>\n      </div>\n    `}_commi',
     '         class="schedule-cancel-button"\n          @click=${()=>this._callServiceObj(Ct(t.cancel))}\n        >\n          Cancel\n        </button>\n      </div>\n    `}_commi'),
    # 955 rename
    ('s._callServiceObj(Ct(a,r))}_renderDum',
     's._callServiceObj(Dt(a,r))}_renderDum'),
    # 956 rename
    ('able"?h:u`<p ',
     'able"?m:u`<p '),
    # 957 rename
    ('t.dump.ends_at),a=fe(r),o=a?Le(a.getTime(),this._',
     't.dump.ends_at),a=fe(r),i=a?Le(a.getTime(),this._'),
    # 958 rename
    (':null,i=S(thi',
     ':null,o=S(thi'),
    # 959 rename
    (');return u`\n      <div class="active-hero">\n        <div class="active-hero-time">${o??"--:--"}</div>\n        <div class="active-hero-label">time remaining</div>\n      <',
     ');return u`\n      <div class="active-hero">\n        <div class="active-hero-time">${i??"--:--"}</div>\n        <div class="active-hero-label">time remaining</div>\n      <'),
    # 960 rename
    (' ${we(i)} \u2022 s',
     ' ${we(o)} \u2022 s'),
    # 961 rename
    ('ed")):h}\n    ',
     'ed")):m}\n    '),
    # 962 rename
    ('dump):h}\n    ',
     'dump):m}\n    '),
    # 963 rename
    ('">${a}</p>`:h}\n        <d',
     '">${a}</p>`:m}\n        <d'),
    # 964 rename
    ('mpDiagnosticsDetails(t){let r=[],a=(o,i)=>{let s=S(this._entityState(i));s!==null&&r.push({label:o,value:s.toString()})};return a("Sta',
     'mpDiagnosticsDetails(t){let r=[],a=(i,o)=>{let s=S(this._entityState(o));s!==null&&r.push({label:i,value:s.toString()})};return a("Sta'),
    # 965 rename
    ('Restored OK",t.restore_successes),a("Failures",t.failures),r.length===0?h:u`\n      <details class="diagnostics-details">\n        <summary>Details</summary>\n        <div class="diagnostics-row">\n          ${r.map(o=>u`<span class="diagnostic-chip">${o.label}: ${o.value}</span>`)}\n        </div>\n      </details>\n    `}_renderEndDumpBu',
     'Restored OK",t.restore_successes),a("Failures",t.failures),r.length===0?m:u`\n      <details class="diagnostics-details">\n        <summary>Details</summary>\n        <div class="diagnostics-row">\n          ${r.map(i=>u`<span class="diagnostic-chip">${i.label}: ${i.value}</span>`)}\n        </div>\n      </details>\n    `}_renderEndDumpBu'),
    # 966 rename
    ('(t,r,a){let o=this._confi',
     '(t,r,a){let i=this._confi'),
    # 967 rename
    ('ton ${o?"conf',
     'ton ${i?"conf'),
    # 968 rename
    ('mpClick(t)}\n      >\n        <ha-icon icon="mdi:backup-restore"></ha-icon>\n        ${o?"Tap again to End & Restore":r}\n        ${o?u`<span class="confirm-progress" style="animati',
     'mpClick(t)}\n      >\n        <ha-icon icon="mdi:backup-restore"></ha-icon>\n        ${i?"Tap again to End & Restore":r}\n        ${i?u`<span class="confirm-progress" style="animati'),
    # 969 rename
    ('ation:${at}ms"></span>`:h}\n      </button>\n    `}};A.styles=[_r,Pr,de`\n',
     'ation:${at}ms"></span>`:m}\n      </button>\n    `}};C.styles=[_r,Rr,de`\n'),
    # 970 rename
    ('\n  `],O([Qe({att',
     '\n  `],I([Je({att'),
    # 971 rename
    ('!1})],A.proto',
     '!1})],C.proto'),
    # 972 rename
    ('e,"hass",2),O([V()],A.prototype,"',
     'e,"hass",2),I([U()],C.prototype,"'),
    # 973 rename
    ('g",2),O([V()],A.proto',
     'g",2),I([U()],C.proto'),
    # 974 rename
    ('ngPower",2),O([V()],A.prototype,"',
     'ngPower",2),I([U()],C.prototype,"'),
    # 975 rename
    ('ndingDuration",2),O([V()],A.prototype,"_pendingSchedulePower",2),O([V()],A.prototype,"_pendingScheduleDuration",2),O([V()],A.prototype,"_confi',
     'ndingDuration",2),I([U()],C.prototype,"_pendingSchedulePower",2),I([U()],C.prototype,"_pendingScheduleDuration",2),I([U()],C.prototype,"_confi'),
    # 976 rename
    ('Restore",2),O([V()],A.prototype,"',
     'Restore",2),I([U()],C.prototype,"'),
    # 977 rename
    ('mpPower",2),O([V()],A.prototype,"',
     'mpPower",2),I([U()],C.prototype,"'),
    # 978 rename
    ('ngDumpStopSoc",2),O([V()],A.prototype,"_pendi',
     'ngDumpStopSoc",2),I([U()],C.prototype,"_pendi'),
    # 979 rename
    ('gDumpDuration",2),O([V()],A.prototype,"_confi',
     'gDumpDuration",2),I([U()],C.prototype,"_confi'),
    # 980 rename
    ('p",2),O([V()],A.proto',
     'p",2),I([U()],C.proto'),
    # 981 rename
    ('umpMode",2),O([V()],A.prototype,"',
     'umpMode",2),I([U()],C.prototype,"'),
    # 982 rename
    ('ngDumpSchedulePower",2),O([V()],A.prototype,"_pendingDump',
     'ngDumpSchedulePower",2),I([U()],C.prototype,"_pendingDump'),
    # 983 rename
    ('heduleStopSoc",2),O([V()],A.prototype,"_pendi',
     'heduleStopSoc",2),I([U()],C.prototype,"_pendi'),
    # 984 rename
    ('uration",2),O([V()],A.prototype,"_nowMs",2),O([V()],A.prototype,"_mode",2),O([V()],A.prototype,"',
     'uration",2),I([U()],C.prototype,"_nowMs",2),I([U()],C.prototype,"_mode",2),I([U()],C.prototype,"'),
    # 985 rename
    ('k",2),A=O([bn("',
     'k",2),C=I([bn("'),
    # 986 rename
    ('rd")],A);wind',
     'rd")],C);wind'),
    # 987 rename
    ('xport{A as Ec',
     'xport{C as Ec'),
)


def pre_epc4_bundle(text: str) -> str:
    """frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js with exactly epc4's edits undone (a frozen reverter of chain entry epc4, PEX): its text as of the entry before."""
    return _revert(text, DIST_EDITS, DIST_REL)


pre_epc4_bundle.edits = DIST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_epc4_bundle(text: str) -> str:
    """Applies epc4's edits to frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js as of the entry before (the round trip)."""
    return _apply(text, DIST_EDITS, DIST_REL)


# The frozen file this entry edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    DIST_REL: pre_epc4_bundle,
}
