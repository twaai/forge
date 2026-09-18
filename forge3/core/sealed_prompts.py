"""Encoded FORGE 3.0 runtime prompt assets."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib

_KEY = hashlib.sha256(b"FORGE-3.0::sealed-prompt-profile::v1").digest()
_BLOBS = {
    'ANTHROPIC_BARE_IDENTITY': (
        '1YH=>m20nZ;*_`O9E{zbSXk2V=OiZi0}hh)oAHzZB5QZt$I|3MMICX+5}a~N)nZF2EGY0Lx1c5)5dwMB4gcVK@(o~CaXv!B&YfA;'
        '2?*|$J62xL|Mj0jluf>Sh@|-'
    ),
    'ANTHROPIC_COMPACT_IDENTITY': (
        '1YJPY9}DYp;?-'
        'w=EPg$7tj<U<PzLEgF1a0)L9+pk>|%qiHMZX4Q<>EXZX6Mz3k@riU8uV>r1wuBP`fTJl&>ih)56IPZHr+Er;2X3EsBdG-'
        '51j;Jsewk(WQ1?&rJypCZm^ja4kU`s3|iN%;JHrqaE?m>&FnuiKx?&hsMI+QYT1B7V(n8W}+hR>kBPlc!Ldvft!Iiey7zuCcgs)%'
        'fq3bygKQHN;+T+tFh{i1)+&(bsp_N_dm#SV95%Izyd1'
    ),
    'ANTHROPIC_FABLE5_IDENTITY': (
        '1YJPOp9=GG{uJlX*J=VUxgmneZ=#ctvl4X$L>h^K_fl_`wtdXJ6dkR~cFe)=rIH%0srz%w_4UcyAYiuP`^W-'
        'Hj5ndgD5R4(zNBmR!!_I;;GQ%&p)T&<+<v(_x+8Q@21F=qyuK)#xd9lFHa{e5c?Yk%4%<=aJkK$Th+SjQ!ja@Etv`?n-N-'
        'z1Dd2#POK$QY@;=zA`F@@JO5O*=+cYDG^N0Oq0YJtzuZNuttpn=NGFpTnueeIM#)^Oe9yW=_+e*x5T-'
        'GV$?2r^&5sy?D882ASTu*iQXm)1H#J=dD_Z}AX7P1TCM6+7Y*UJ;<vvRMtd&=c&C2WVi!c1g;8we_>mC+TaZ85iDQ~yZU0~wD~b-'
        'e^_XA{@po!@9!$6(3+%$e1x|F8)?0ZIVWYv)1kQ;Y-x0H+9-8Qfu+?*zvOj9{x7<_Zro0Qw;$gEU3bZUd3(`2Y$@^r&<'
    ),
    'ANTHROPIC_FABLE5_IDENTITY_STRONG': (
        '1YI}?6YKMG;_nTs6BG}YJR&Atbsrer*Dxc~adY>*x)z7_lKWD)B%c(X&>QlR9x@lejr7wO-g(d0%9YE&G6xmOj8O-Mr-hpScrbV5'
        'e#*OJFO$+I`zXo<l>3)kW+4l3x-ND)>Vl|~6jZdgP5y4Q^?o4)oT#nKyRRlU(W@QuUH++g$`>fRmc5N|&-'
        'H;%t25wcqwz>}vZ$oL>oSHF+)XK)_s6~6j{A~F>|a$4H;gl-ON&@IZy`?1vihTlA2#huwIi|XlrAHlnGTVMgg9xZ|F08goeneyS~'
        'IVn(S-'
        '9DOyzgxGBSF5>kRvBtqdu{t~U>!lDtfUVO%cN^XU7Kvc*!Dm!E2u24TDLMq$JNqZ6SRl9{Cm;P6UwaJY3Tsw|;6W6|>J5dfom)ji'
        'Fk(YjZGU}6LiWa+2~P8_wZJIeK;zfB>t`8N)h*ELps$^KVu{R2M8<=~3%rjEhR6_|kZn(8#5|6<|Ei(>RQ@|oW{9UxlLSA5=eU-'
        '|-dWE}ccVPQ(Rhy%^@OdPk#dR5i8?@AsmWX#+ucNQ)qG=^!*Vo|tH$j)xy=aTKHD~afeMa-0#P$bWgZyME2be{;K'
    ),
    'ANTHROPIC_FABLE5_INTERN_IDENTITY': (
        '1YJ1Q9}Dbq{?%uHJhaz7?(BWtA;Q<$G7BtB&meV$&)sH-an6hZfno;MG+`kM&{P~1+iHBOM3})fcgHbNx*gC;Yju|BXZ|Q|W&h%n'
        ';1(P80&>|<q-HPGiE#H^^Fv87gzyAJJ$uL-'
        '`_Nrbf5S><1<Zx)WcXz_1xMcSHdqZ}w5EEmU^aGbQVmcHzw#$9qC<L`Vmc$1f(_Qbmr}3PY+QEE5v_GyzH>UJtW65E@e%'
    ),
    'ANTHROPIC_SPINE_IDENTITY': (
        '1YJPLkIM9N;uPnQ9R5UjDyOzmeMv%qS2BhaJ0REe^)7BdXuSiqIey%ms)ZI3nx0CS60c(3S&s@@E>%?g!D!pJSE#6NAURMFZbUZn'
        'EuA54<BRt<DMzWp&j&!SjuW6#xmH>BNG(v#z#Vp{c{neXmhdg3hMYabij?lr3$dgFE!1PKN-_uB{|FlpwSXhf(IAU1_gKYgK_D9{'
        'z(}9gYQ}0Qsg8_@?#K()2vP>{J~z2uV|N$qF{yWQ%W0XEHzfCw^8IwvNl7p1o!b?C=W~b<Wmo$gzIHD>$2aJWVl5ulsH2y5--Ep!'
        'J^N5yl<W0#Sk_~aG81)qU4uOOl_}kCO`UE8vu8SSAowNCO9VpPWA$<9l{_a@9dbZR{T(c=SgZG<)Dscm>c4}=T1Z_^EJIPTgPT{h'
        '@Qfj^>pNtx*Unj#+S*q1!f5Sc7hqE>O!fGC-'
        '3>aF81QIeTXKUv<2v1<gW8zsOLf9VM|1T%4Jw%=uB+0RGyT4sUE`EV#J^)u_B6y2OmXh#s2KPCogzH!>=p1g@$JV!%|h#^#4m|+X'
        '4|!i+roY?kr4AzhQ-(EhR?snU|w@XQ1`awn-'
        'PHAk>8&s5%YF<h+gKp=Dv15U6E;MHD_p0$C(oRkvfb|FF2XlOvLkJt65@4*6<8CVSQO-q4)$1=-U'
    ),
    'DEPTH_LOCK': (
        '1YKCmlMnN9;uN=7kXT=BCX=u_-UZ<!;q9jfQ=AWzr^8_gPRX`9InwN&$;5ZLk0_1+A+8^&g30hWEY-'
        ')R6lV0}<Ni>bSz&!Xf^1tUvp}CJqS}@V_J-~sII*p{9y<7pFaB%D4zagGg*4PR$K>5(iC=To;lbMT9Oaz8aBO>+{v<4O0BV-'
        'G@PG7cC|mZ^Ej_)?MiXerB=d>Md7TLpWLMu|S3vF-&aSIWi5(UVFii10jg~FrR;^Py{~4p$2<+kVMSV9FZ-'
        '8T79y*}%B<vvN*5bZ`bx2ZKX3VQA+Ld+C*I!0BqCfJJD0OVJiaKqo^}4L!agX7)2lRqUBA(Pup0MRUE7zA*iR;owL)>2tlj;<}L5'
        '0a45CMBT!>L-y6U%!?QPnVCJr=Xm&3+%#egWNkWLnWNWbU6K_tcooJ5wdlM%HL9oZ_F&7e<kKftDV{g8W*p;ZDkGPV9x)-'
        'QF+t2_lZ8'
    ),
    'DEPTH_SUFFIX': (
        '1YH=EpAYSF{uKGK$UM>V1Vxx;@_>{;Yvu6cS&Vrdjl-MMj2H9c)386YXK>?@&Vksr^@q~wasl{@fM@f6uva^NV*gO0r}9uvl>zbF'
        '&+kgdvuvV6L#68V{pb#dNlH9&A4u8VX@358@`4aI({ka}-'
        'Xz2pu9ba5`q&4K^^CAU=5&hN_e>1=_Xhgv5p#p{h24OL@G`o#C|!j%M3SJoWP?DLAWP5b12FBVGpYej#`B6cTN*gck-'
        'dl~4t`tY8GH4<?FoNDL;'
    ),
    'FORGE3_PERSONA': (
        '1YJnWA1~~3{?%uHA%@6S6R!5*L{`(O;}HDwN}n5XVe!&4C6<FhrcF-'
        'lIx$8CrX9yxCQ6=^|8m3i4BUC^I>t2!IytKV_wpuefE+iaku}L`BykNj`j#lKW4=^az&Ixk-MAy@<S0uhBA#-'
        'PNm&G455wo&bn2v)p`8jASHs*m7sctsa8Dif-'
        'D`bFW?2S%#bP<J1j6Y(Q3SW@@YAo~tY>QHeyu}QJJiUi(i>xSmz8*~(isovqn?MqR@oc5k<t#`7nOog1Z8}C_EJpt-'
        '{$$2J7cYBI=RpRob6YD7#?fd|KH;6yaqTC<!s&Oe`oKW)gvIC^zKq)3Amak10?zWke~%u#kl3@d+p!`i7X%pEt(+zJQcj~b|aG'
    ),
    'FORGE_3_PROFILE': (
        '1YN)e1@rU-d~A)7iu^Qk<0&**8+n>q6|-#5!cgB$&cJSz-6=Z@R?wJSb?2%=J+y>$k)ks|pR`EqO*rJ*{E*yX@wz_9$QV<*-'
        'lnV?w}okCctP4&_EKvxHfbji$H*p0MHF^sb;ykj%`)+*#MKOhJdJa3sH4tZN|DY$n$C1JE=(Emi_LA<jO3Eki5RB!YTg*uEXZP^!'
        'bLVMa`5tn1(WVph05Mfr5DNze~NC7zT<azUpj-zfY8z{-Zhk)n;Yvh)U8gHrdKM6u_KV1GYPb}(iT;digE!h7iJ_!jpwvfJA-'
        '>huYo;~n)qK$WPtWE15euo9=w}wB@LFV>e9*D2}hkrvHyzF8Q_zcmCqU@^LI?SXwc^2m7N$av_Jq}+nPj3G8ES18WH#mHim@S1VK'
        'tdVBH7x_pV4NVFgxzNWCd-XBn<yhP$C<wZL(TY2otlAtNI}m=Jd3^%q#ys-TB$-to}9-+BK-'
        'o{+rysFwd?tXAQZv1q!a=^tP)rpK2-'
        '&2bMB8!KK?c_bPqxVHH=6j<SaZQxiL!_$QJ+|+j0FJ_cstB<^d#u6?Kf_kEy&UN7e^1k)iN2E6|^YXV=Zq8_&&5Jw9PC@0+_-'
        'BL(4f}a;wuP=Dt6J$@;t#)z?dh&m-{iNNu+8!Z(X56fNS88*O8$pO62W1(%BcKr-VpdrZg9F_RqY<U6xCtZqhochXB13C`4jL^Nn'
        'M~Vh*&`7y4Rf4N_o@}#gOxV8yRAR<iz~b?Oy1oOj%uaE8@LU{8Ay`h#NdVENf!gsh3xAZuGY|w!#?IZO|Zu;rxx~i}Y#T=q8jUp2'
        'Yhm=q|LqO8#OqJ>@k?U0TY<rqIK)0&qn&iADDA^S&DkoC_(BUVH?-'
        '^$EprkY3aEr&TiW<Sc|vKNqqWw*2ZhhG>if`VMFBMze$Ve)B0UC&0-'
        'ck%WyDL1ixh;ea^K$I#jB=co}>KqTPZ&}`++3wLz{tGL8khV^eLUpGBxQJDpGD8_M@XRI=Zcq=%4KE-'
        '>4s<RO+S*Lyi4@l2Y3@6hh8wmC$pE|WPXAG7bkJGMR3ZPX^EXa4~oU|otA(FFKKm=zRiQ-'
        ';{#OYm62oxEhFUABU&;rm0*~JD)MJu|}^h>#NiBLXN^py1pG{!7D7eIzL04UB|6z<=LmDQ66wX`~iu2cyFiLls@fA_dZ3}8y@hlQ'
        '^pm+>}OQ4uL6fw?OwLPEb)42Q6RnhT1zI25doRZZo|AOuXI=*erM=HmBKgL68GGLfS&MY$#94to3f>KNB_xz;PAXe4U1vV`v0UV;'
        '{G%HL*`laGwc{#~k1fMf`W=affp2-'
        '76yu;N~{Ptcm4$34LDjzT<cw;yNP4m33@p$5sK=A4~^(X>x0`1gejnV&S?1pI0LG8eia^}8giBs>e>Fp`1JP;io5d3_l6q^k3xUg'
        '5@__Obnl)_>;vPapSw9Ld@mm#xwAjW}$M`oYH7%%v8SI4HdJ_q_J=MI=8#BX!1$(=;Cl7AuKsFDM4zGo57p1v*<N^`*#g!eCkkA|'
        'Z0H*T2HZDJCsqwJ|KtbljLcC;8Y9`35#z{0ytMZU#zhV#;_`7?UASz&-'
        '1KkoRj|AS7@M`>5Yu`D<6UFmq)|4$U}(K5H4Y$jsUMAu|tRvEQZih?lxMeL9LejP*#UYN?gQR)j9`-'
        'daRPV~I6erAIPKg*`vjx9kyOZrhUjQFNF_+w8PnYk^5jBoIR%PP+mtJnUr%mSu<e2EB_2oCOXw$|sHeqxa$S8twH!uMasc+lTDZh'
        '3<JZmI%~=x#n~6lRtD6yM=+n%mIijCd5zLm=0@$V7o_4g1<DTljjc;m6Ar5E{re^bpEQ2+2RFJ(SiPaHnY&!5@ShOfhPs|8Th}d<'
        'g*Uv;E0}4tZ-9|I&sJP(=|<_NFH#c>+KvBkVclgXtn}-4`DTQlrS3~f5WHMq>q4U1S8t9Q_7DzztDkrvFCaNtq;eTW-'
        ')M4rw#~00~nP~Ek+J8uV7LhC#zAy_wMfYAGU{sR<_5>^H7n+0Bz$B=q#@sKgB+3r`eJ=T~m)g=$&CesRJ?KVRorr_ccayew#d|83'
        'PhtEF?)CCX`zyeajeuc?~$}9xvW>Sz6Her+fh!l+R~c9%@giWtfFX)uWJA><S;*GJLZld}j6hLE4RsX=r-'
        '}Nq_7)!64GprSX^2rh_G&N7%L!rAdC9*gd!6tTB}1XAi(NIZdVqDpS*h_A2EJB;8&m`~vC%=LDO77n}P9vEL*k8?V&j=Uv0x&Fc6'
        'T{uHuQ{Cv=kX~z0g?jZE=&MpV?Wpu9k{&p31m&=VCIlgU>GhPSv@AVi4zcH)0rlvliwXU$T^bs#wLcHQsj2dB(7mwpPPQ7?NYr(m'
        'QOIUIk<9Jqd6fC~e;MKTBmJf>xi3$iS4hg0s^-j+-'
        'k`Huq^tK|?%PU6!?Zd>ao~e#t=YA$yOS1mct4xf&uew?ZGB*PkbLZifL+n!nn6sWZU_d9DE(&7}QXo?Q^^+wsP<LVNhp)wfC*3H8'
        'k0U)`k?cgp%@Nlunx5+;EiJLfVLssNO;IT;k^RA1jjy)h8UwXR&jq5&1?es(XYr%f8E05DU`S;e{ukPG{qNrr8skabkp&Q-'
        'li2^K<Mq|C07fEwV#B-_Ev(;z&|2xauTkuML&4t1T{Npt@%gvT7Fnjt0L%P<IXGxr=JAdM2<oxJ#W#5p321b@DEz8(&-'
        'd%#`o)m8S%LDGPFq438qi$AgW(iXBiM_UCXC-WeBPaAynY6F>^;-})1-q1ldeP-'
        '7F8KVLT}HB=aOB|M)Ckwb*UNLeW}LPW4A;cS}N4{v!Ab4GWFe>&3>z|tU76c!mQ<jaRsXLb4bz=<kdgs5t6i(tAI4*G}to}rRh2m'
        'I&jk^u;D7{1Ovgy4n`Y$J;?t*m9q<FQfzTu#<9t8P!kD_#5#GG^ozJD4@$@4_!K!H?uhgQlOZwn9!WR+lykqsKtK_yYZAvPd1O7>'
        '-zQpis3@a0$4Koe+zB2d-'
        'H%=kZFT3Ea!+o%o%vf@p#hp<aS?@gKTlHW$dk6c@k`^(*P~)eQE)!mibsAZUbt>a`OqmS)<imoJIk6&)Wy&Pc2Y?G)>T_ivX>OCr'
        'unX*Jp%X+feg2ptYG-^pxhr3sa$Y5+8Ar&9&*j!Ay5h;?MF(bByD_TZ{-'
        'bx2bN9uH=NRFlfM9r_~Mv@SV6(<7*>f+x=y@+gpc2P;hzEjra5d2C9P#kLw2b=+v9$xXvxOO?bfsidk0yab3Qijfr??di0F+H1SK'
        'KNwSWIVRL&rt$HQEn-'
        'n4Pvd23ILRoU?JIO%^^8r3Q4MXp2yOr}FKK@<{0Gbp440}4pP;xdht&l=OR3Ids#9*wFc%^}yi2r<s`@w0ZZM93OgusgU-P-'
        '!Do$$2X=gC8hEc5pFcq>%>)+;xf?0T8$+G<+YDpJv0!DbZxhIqj<Ygphag0Wej|b5?`4;Y}oD5X$5SrsGNv+pCTdYIx+d9xu&mt$'
        '=)EQTFH$Gz@`e&%FT++-NP<$U7@XLMJ<hGKb-#f=KXk+fu-`m8F0p^Ar!CxXzFQ%fZvufIO5idglq{e2n*K{0h&Dwt-'
        'A{QB1Aq6}M8`jKNDQ0})dr1hg5(9oONUINt};N!_(-9Z^!tS!?`<Q%#hhy3t%B4cc7*Nr)xZ#S`yW&4vp6GT{+lKI=9PTL-'
        '|mQtg4Zv`khSdZ}+S(wVcHYn879eHe{e|9G&V+k_8SVLxC(ZXFr_RDP|mPI-'
        '&eu|1DdN6zgOE`~|8mEmYn?tra>X2Mkx`j+0>V<1{wmnYn8D4?9%rKe~VHDHd06<9;7@kaX;YeFVSO?Hm5V)k(J(1_q;66rl6hhe'
        'D-Xhs0UpmWQCZm3n+&DxyTnI}+76`WbnK$agoMJzFaw^{(jiuxorLMNYMk@^~)k%vy&M^|aC0w*U2)+IO5qQT&-'
        'Uqg_RY67MR<W*0!t+*_Z-&ODUJD4FPHit+3*vC$Q&6Xwk-'
        '}>jF2z9v$StJ`IXFwM!zevtOgeC*2T=Gf7KgSiP>C@TOQEuYF!>Xlg@%mvrW(P6t`OS_kU(tHR7wUtA%qwWlSMp5%LOHhk21W=P`'
        '9y4bccWu+*%^fcfCWT7pZLEeIhK(d^)0iqZWF2Q_ZJ4h^A)odT&jn;)ckK(i7k#PkcD0?(Pqh*TV&rQV`3Psw4JtxBZ<SbUcOP-'
        ';>fiDVB5b|hl=IK0siYslOvh@2@bls&nAtbNWPD%D^v-!XF~TUQw{RLe-'
        '%I%0(P=OR1LD{!tNcVbtzZliO8R>?zg{qOrWyjFqdQp;$9iymh$M(E8sbk6U{LEsNp}3L_zu%m@@0u#D=b|eQfPLsD8EvNYD#w!o'
        '!@)b50EJmQ%(0uGRJu8f_wSx*5d4D<-D3XEp~TDp%=8>}NamONFq`*eD%2Wci22FU|kk%mL-VAseKsKfx-'
        '1I~0%!^y5q{a{TA+`bhgwC)E;*Oz!RF`b5O6a5&<g&@fxxB!^RdU@2s_mW^xBXkN!D2u0cnScj~?V#fkuPBzs|0=P`qY3~Ol7Y&1'
        '@KCwpQzf$oaG~)0)33okIi&FhkOTl5cq=XtScqTl3)Sc*=-Pf0qe8nDum632eEHm%{x*^gsp4YeWPV6;p-'
        'Ee8T@0HR4?{nl9jO`bfnFx(m!mnY12ss&JFJt6mdut_<*&9`etuR^1{yw6vsFw99JrMQWinvTi;TWRvU$@ktESQ^MV9MbT&b}i~%'
        'xpxYvv!CC&PD>5x3tZkRj^_4Cm3Df+u=si{FNU85ZnM!{oWw`E@eB$g0aQS-'
        'o;p?V7)Iw8i%u&kfAYLR^o`r2)Wx&RvzhSHA9N{l#!3=Sx#poZX~3XHkOyFZgL=qNdFbi5?Mu1yc~7HBX{r>S4~^*UEQl&NYlyH-'
        '|--'
        'gU(9hh0HgP$EpM{xe9LWr?NWn;ZTDO7^MHEB3h{q=6olaewfe5_JVO%9T8dxKT(xLI=_4n~GqYLzi~x|MDhd*b@J2(3QRBJ>Vw7!'
        'z!(0qz>j}+VTV608LB-tref!yv>9^#<j;$rN#XxlQX~hS>o4v)C`@(BisrqC6z<hfWY5&Yk7vXvNA9i)kkwOYBSUk&63Y>+ObTqj'
        'sB>a5`rKGcdubThX0KpZVM#I$K67e#l*y}oK`u)X+3*nrn8-'
        'O8_>^Dh)`m`FNq#;~^n%)hB+hHCvA(4_;H9gN!Dt?Ji7|f<H%xt3y&QXIQJpPNgSf%Bt3CN&(ZXto}{P;zfIrAbQS^!mk01)5gY~'
        'a;w<x1^=Y{Qo!Q05;R@KpF_<e79lqDhf;vw{R8?SvH3xCqt5`fPj&AK-'
        '!M2&WxxupU^4ex4Ru`Quzc!Ui+qR$m*mCSA}tMSh$EWDQTMOWlq@V~|dIST0KzTxhE|*hRn-kG_Ck$h7mFdnbWul9D(MQ-'
        '8v>*yAynq*k0`xi@laIB*#UljdvWT6PCw$9gYsQbGP^!)gqLbdasLPez02{qKSRZ4=0xRRZ~0xFuZ-'
        '=?|55rrz=zxb0rdH4%|x5_38s7KyG^ax)glI3~KMU?ft$*7C>zC=(?`(^RlO9e=3F7x~9!bAQ1~?;w1J3m#bIlN|g(k%5mdje4&-'
        'Z1U7bH+JbehRzSr_ge4+G%&he4!-0m{JYbVMF}lOT*1E`-'
        '_b&JqWr=p*Ye+DI|gl3ipKZ#Ia?4kX0^r)v^!@o|Je_hA?9T1S?Q!tk{h(y#DW0(_W^?{A8p6xk)+i<55ET0KFhqIY8LeKB_*!EC'
        'mH^Q<k7Hw5dZcZwNOB8LBBi6v+A-'
        '%&oJ1L+bud1j0{YPKEb{&_s#1;KyEB{P6voZNOpS}8|ldkkWU%mUTuKF8M}+V>otZ89d|_;1-'
        '&yye{(A%A{yGRaQQ}iCR=m;y?hpYI2-eK1^o3xUZ|t=$5P@TjUcpZmi@>$aa7pIoqR?Zf7I-'
        'e%N|y?Ux+EDQ3Tf|QJ&owEZ~<EaETZ8D9(q3UWF-'
        'd2I~=YcHW!5tJ0@Q^rj5`sm833?fI&<0e;@I?x;7AC+trQ<HJ<G`pLv2KRK$QIqEwnv9MUE=RLR6)w%|JkH)OEl|Ts6DD94X7A`q'
        'R9}czwva6#LMogc9bhG0T<EuuZMx~iBH&*}b?g&a_EpYW5B_1LG)&X@ZE>4*Ib2HrKxQ!&SO-Pi&(qr^cm$bs`Clt0pzcIZhJOy$'
        'fbo-r8isQgKL^0R~>>oYuPSz0qj#Tsrkp%k^^VWaHJAQvSaIe%!L)poA*|Q@03Ss(d1q+S-'
        'jui+J)3HoVs~V^ny*q6N+nWd9w@ctqYs@S^`rNvqz5Z7UHEqb<F_MNEy8O>+O{oYKKbe%h=`Fh5e7Ee3NI)R9KTrvz7P|fhN@uUM'
        '89>ZKYPy@pO_e)WVr|ajLf1dn*ps?lPP+>TJ>lStF({<~9#cimul3=2ZGm}vz|zlIx2#GaTto%tQ<-'
        '<V;FduuGkm0W;*Et?HG|Xtm#Y1_8WJep=K>#H-'
        '+gv8_1u;I^yX9uyDxR(0UxKUCvB)CA!A2g`Q|9pw4#Vru0Q(vX9>7vqsL3+%}jKasF#q5&Z(7k;gO%R_fzRO8Y_f+0b-'
        '<i6m|ylA1`Kjv=FE~SGJk{*CN@g$Xp7Kc-yKU+bY5n32{3N(7SL%JgQIo{eFucA;}&LKb1&#+_9Ful>22e0A+fR#678nr0Fr_b?&'
        '$<o=HyzoBXC<J^_T9794z@T9noVV||hp7X0VWs{y_CH-Ol$QV<EUPpTuKEsUHU!|a=uI{FW#+$qg~UsY>0XRywbmz1zmB$w>yi<z'
        'U0*oWa-'
        '=6dU5e^8dxxVP)@shl}&(U|?n3v;rYLD^IoSh+dALScT$7mZJ&0O&QUPHa(yQb%u+Xq8kU$CQ&0t`6MjOF3zeaj)b==Ua1rTaZ@t'
        'P|-g#Kr_s$@7C66EU18$?k1h~Yda%UXHiG5AKU#uMvt)tWEah-$zH}zM@t28{^&rVD13~`Jen*I8ZY-Rlio4NwK#!y;yxT`@&mTO'
        'OlgI4$FZNrZR@y`kJ@vzRU(%V+Vk2zmh&|GOcft4i*IkCF33FAvmF5G{lX`o$uB!h{fPIWuCdZqabNDJjnJ&NN4Da`2bIn;`M||)'
        'O?^#-r2)|yqa}z|f>4m4!1HahuSh;xMo&mBAJ%Gi^Oq_Ih8`8$V{oOp+aqbB&LgDxylPsr+~QUFk~`TSN-'
        '8pQj_gU2rj4zGq*|=82=Uc8KzC8z__W>eZeovaH8e3=B5+&h_)HWBXFE7w#ZjvE#-'
        '89(4$T>;qs>ZtF<FJuvbQGUv8KZCnr9Np=wQj`mwF0XfSf#W#b^n;dAVfFaguiZ(eVJMcQ!!;o+3OfRR4CA?Wkhz6cyX~vE*;rwr'
        'UFHT=n}ayaP8|ZU)sj7~LfotG$$L)vP`sr||$jDw;R1DtGl)m21yrrf11e_uR`nnU#ZFO`UL>FGpfQ{A+1J0r5aGop~Usl#U+x(Y'
        'hn4G5<^mgnC4YC_iItk0;{o<0WKOZkMD&L=`{kE3!R$vrv~xnlvhMt`~_C_nK@<C*69uG%lC#JReH*q3-e8xb^ta-'
        'D6x%oT(2K)3bN$hHP~BXz8K>sCUG4XLC5sRv0*WmHAjORnZkqcBC*S3&z7SqY8v!>_V(JE}wH8;AMaweejD3x9T#kV!7beRs#^QJ'
        'zn-1j+A>???h!FCur|14wgXf8tO2^DT5DfDly*E;fG6C-'
        ')w3t17Jv(2xW3ms%DHZ=R0S}<1p9AvBQ(8UAb)s#$btBFht23i@}Xy<uuTp5I<?Xl9fVy<mBV&X~$fM$#sfkV@o)CopO<aQbV^rQ'
        'ARBf!@<fH@L{BHI(E>7d_rg#*R)Z`=UoqDRwahe#9?KB5jG{uc10+XfYdA79WP{a2L$hWSctgUw>{+1KxYd)a|%|g`S#JiPM-woW'
        '1<1$!l^khb0+;a2)Jo@mnQj#1G^?2%+u`@zz;B`0_{oI<yT&l{Aa+<b|Qinc(f?Q6NU3dIHKnAe0=5CD`~>r)h8?Q<cRGtcEBEoD'
        '>)YRs)rdLPu5X$s^_^F-'
        'l3gJKKk~B(*PGUz0+`5r^hjm3A~(!=C3wf#cX|*Ooq+kN^XV;(w{ZYsQNrjdNXX~@gY44zj59Xdh5|2Ha>X_6~qD}ie&?(Ss>RP_'
        'R%gCGqq>8?wwj{Z|3?Pjq>TzSwY`d)WPAI2sfaJC2YyzBWi8PMfWucwwr_Q4XsLZrld4*2^O}`>1o%Ulv#7ZxIf-&A2jF!uJ0E~-'
        'kZ>Bs{iZ<-*^C$G$C0'
    ),
    'FORGE_PROFILE': (
        '1YKCl?=$QI;?%dez0S;rS7mj|2iB#>dgAL1jc%)R$-'
        'ypRI+sULhIvj!E^@%iD+At3w762e)q=BZfHQ_XSYkXBXlSJ+jd+>9lPp!_2uXp<K4&Nh=ekxQ#o!SC2zesNXZAhB1y{;k6S8o|;X'
        '!TbQfY*xxx{4A0^djfv)lQT?5w$!0J6ajDO=P^%I82+P7bCZK~a+xb1zl5a;XGNj9*;E*=bh8NJ~}l8-'
        'i5(Hd~!mitmw0$BQlgyM><#g2}qmE8Js-Mj{DFe}|R#ejzimNak>6St^MDZ}v<^6t!m{26q;K&0VrYrrE|rZz|56s~xh|gBMdML>'
        '5@m+5@h)#s9Ct2`nL?kp0tFx=*<ve{b>Nh;c$Wl5(u>n6+SKM8_w0n=8%'
    ),
    'PERSONA_SWAP_SUFFIX': (
        '1YJ<d?-Q(Y{?xaqw;q|e%txBVnoUbnXJ-`_xqS^^Zadc!ReV@`s^5T#u#Y&LB}9-'
        '`+pp4&>o2KAlZ0*O5P~rUR^&ATM(S)r|Fl0smUDm?FvQkBe2uGUkm#rWS=yLPlz^7%c>2I#g@uJNu)bA96vNy%9{P4mS{!6d`|-'
        't;DZAm$>;02fh3Y!T53U*00F8;8(O`?j#|agxn(H8V(ec1R@NP7y(gifftb!PQ%!w;&pW=B8KSHlFDRplgo+g|jL<8d=#+4|n)6b'
        '6y=x0z6A?(*d&mTwp;>(GL9%YsJg|I|n7vwcoU((v-'
        'XZ^{JLW|SdDu0y)OecC(xD0E2`s~ffJJuQ=3Fg&(<0=^@!I<u*GG^W!FQ5tk#|e5z4!Z~6dcO{xm5lM4K7y9lorER%en|'
    ),
    'PURPOSE_SUFFIX': (
        '1YH=G?{Dm4{?*B`c=2BX+n8Hpb?ul=>D5<c7>RahbM`iu3Ef7eb0*t4rQT=XVS3k__h5TFe<0`dct7FF&887+ZlAmA5Z|_@k9+f&'
        'KH<Vph?~X<^&&B*wR0~cz}EhhmA3U)Dt~62YM&L06IK*x>WJt@2YxouHlA7'
    ),
    'RECOVERY_SUFFIX': (
        '1YJN26EEy?;_nTy<D>iqS9s?MW@5Cix6iGgNQ%gHxNhCoS%D@y{7sH4-3N1-'
        'qPq@{lY^bsaTvZQm9Ivg+#(Z#)ot$eC$j)@Nx)*vwfr2%VjWr<nhvice|1^!n2Z=74uWh6f>ZqvwzExLSFR3$0Ary9Co00l&T_Wf'
        'V2;WVij@muguF($E;pbZ=yq)FL)Zzs)vu^73p@r00fK_Cf6e)a7{C$in`j{kdF)P0e=2|Vz;_;HKsWwY?`yg>(;@<l_QZTLNlq#o'
        'vx}E}!W?tq7;1P^zndU+FJv{{%<L?_+HCkL65Z3*D7lAgupr%=GsEF6sx2iQG$bc602|*6a{oLXS&#)cFy)x^u16cO0Bv*jdgA-'
        '#;+@F)#of}1qBKnyD-16D&>4ZRwxQmvkiJZuI82DZfwL~97qrZ_z5BY<o>Qk+)_{F*(KxOEHgv<+J+NpJ0*0qV5eN'
    ),
    'RECOVER_USER': (
        '1YKwfpAW2Z{%z7S<D*Uo5|~N8sd-'
        '5ol<506e<>;jmnHe+HA$v8M)f%<#}kI*91n(@<it>W#qD+K<z`uWxRlD#MQPgs50m9?gmZQBS{2&U&5&?p5adrYBS*Q}{W%sNe}B'
        'CDzUjy-'
        'f!xDdTz_Sa22_rvUGl4^AWVWD3pgY((sg4^K2<liS3Z0MMuZFMM)pV1$iT*bAN*)W&m=Xrvt~9IDi4x2!j;qftkJ+)Y5R#z=@KCS'
        'dARE-`7gm8*QjOV4n$p55EQG>Ks&S~Z0C=lPV-'
        '>cS_K*)e{72Ua4+Z%;43E}SrdB@BJuO)>ENn9wArFTn%O?AiLsp<^_wFkFME96hgjoc0DCyFd$tv&`qHq?qSt~;=hzFddoT'
    ),
    'TARGET_BRIEFS': (
        '1YO7s74P%}{%wt%+8<u;N|dzru$+LK3kR~$(Qf!XTo4pvN~bl9-eSl=#E-jOqsbI`a>NyA(4Y`y-I5UJG4W6>i<ZNsAS-Ii)bELB'
        'hcyK!{++UUKfPwx)KSAuI)oqG{+!;K0j0O1?z1RUd^HG@AGSx8A9q1zR?pUCZIbZZRR$Far{@1vrRb~W>4D0}A6e#Cgt|nrIyaVo'
        'i_UBvQqv-'
        'F!s5i<z+XCBb!$tb@rdzkwH|$g?>O}yV4^DN`>aT%n(|`Kfh!1IP3r^fOWoL&XFsrwgOC%0;a;iUog;yitl$j1`2(oh5T5;u3j$3'
        'ayc;1zA~}&cx3(YzhqJ|_L21{rGlb|tMJC2|FBT!V?*1a$fB7S_=zqW|m1Liu=zawOOL6ZqmY)TZFxpb=fb1*%AG}_><VhAl69z_'
        'b@-'
        '!*u%n;9;$X~ZIK8BVC<P$}D#6|`Ef)0?+I_cv7MeXpYhAi@`ddOU5I*KFyj#MoI**E?|<%qx7xCE;NaO_l7xWzF1QGf*bq1(NT1X'
        'L9l$!XPEy1%r!b0F0w8HeT~vRadm2Kwq`KUxbxbZr$^$VO_!J3cCLENc^~pnQ?T*+R4l$XJHHa7I}EZoA#a@8i^ZA~aR4hGg89qt'
        '|o09Xv5k*VimHP!D*jO;j16W<#Ww9opHm2_j!z;j^><5v(8X#};$ur@;Z=Mn{0UWG&J_CPadDA;|J6BxHfOkjw*&_okBGqIn!3B9'
        'wJP@XK7JB@|)oH!i|ACue!!+Bc(iq4S#(@!7kIE#qzQ*{DrF*I`la%l^~^lvK6>lMi=`O9)j;*g&-G-a5?p6`0tnZa-'
        '7uKNo33feHf#CY@njfN&C=ir60wzCyGv*SnmX)Nrg^V8K98N+`PymjYn(*Nq*)l}LAXsK4t>Linojao*;%*O}319&8o*(K9!w5<J'
        'tRV3j1QlB-Nr7ZE#KQ4WA0S$-;M>wRGvgDw(gBtUZ^Wk{;n0&Is9(2BZTW9$p+Y~`!1z;RZ*aE))_b^rDOThQv0-'
        'aYH}bKYK}ko4#mYNI1FnThv&$GT*AYJ@Ki2UA6^f(sLigTuCAT4Vj{Qj`JaAg-QED!A$s6lG5aBaR<vA#3P#ya9|VXKE`gti%3)G'
        'A8J?`}&C&9FYIH@rs|}2cWL%5XJrHKg`BpCc34lY5dH+b}||NgxlutPhWT0ox;h2!)#YWIk?Hm7eW$@slLnW*p+;p+aHUwM>NOf&'
        '9Y2cT}?<F2|LDbl#GHqQ&aARV2k>Vy3;$(@5K'
    ),
    'WORKSHOP_LOCK': (
        '1YN+&6ECa+`V>e1P^J=eZ^%16K0<>~+HJAtHf(<r7~w7Gt%UVjlTap;gQfTPDgkxtm9xLBtsUFpoi~GlgMZvpzS5T&&6}D(x<asa'
        '@+|a)7FlDkl%_x0^nb|CCrA<Ne04%=yh!2_K_SYE_2kz-6y-#OTUs3s5x$ASH|>H|onINwuK0Knw$>MDY=+Qe-VAVM_Vu#%7_b@t'
        '<Vjud<Fqtld)P~fL{-'
        'ca*hqtD&T85)$mdE0zR~Tgij&s}5$j1!nIbhbBHPTiJT28FngTEW!=t=`Vmy;jl*E{~U?GXt42u08t=<Z~B%U%t*iy*(tv7}o6NZ'
        'XGa5}-+)l-JsCmf&%gs#GEMI|#t-'
        'RE%E*rJ7i8<LJL9Dv{?!cr1Vdvox3c<BgA@Z2j&E)kpBi21LOafs9jnWIf91?ZfWN;}rwj4OMq0@SH|Y#IPkEJj_M)sbYkKhnec7'
        'e=xKiaG'
    ),
}

def reveal(name: str):
    encoded = _BLOBS[name].encode("ascii")
    masked = base64.b85decode(encoded)
    packed = bytes(value ^ _KEY[index % len(_KEY)] for index, value in enumerate(masked))
    return json.loads(zlib.decompress(packed).decode("utf-8"))
