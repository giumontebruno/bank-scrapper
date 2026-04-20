from catalog.normalization import assess_merchant_candidate, merchant_equivalent, resolve_merchant


def test_resolve_merchant_collapses_known_brands() -> None:
    shell = resolve_merchant("Shell Mcal Lopez")
    copetrol = resolve_merchant("Copetrol SA Acceso Sur")
    superseis = resolve_merchant("Super 6")

    assert shell.brand_normalized == "Shell"
    assert shell.merchant_normalized == "Shell"
    assert copetrol.brand_normalized == "Copetrol"
    assert superseis.merchant_normalized == "Superseis"


def test_merchant_equivalent_uses_brand_level_join() -> None:
    assert merchant_equivalent("Shell Bahia", "Shell")
    assert merchant_equivalent("Super Seis", "Superseis")
    assert not merchant_equivalent("Shell", "Copetrol")


def test_assess_merchant_rejects_generic_or_disclaimer_text() -> None:
    generic = assess_merchant_candidate("Ver bases y condiciones")
    rubric = assess_merchant_candidate("Supermercados")
    disclaimer = assess_merchant_candidate("No aplica para servicios a domicilio y giftcard")
    cta = assess_merchant_candidate("Conoce mas sobre Ueno")
    helper = assess_merchant_candidate("Conocer promos")
    mechanic = assess_merchant_candidate("En caja reintegro")
    installments = assess_merchant_candidate("Sin intereses")
    category_fragment = assess_merchant_candidate("De tiendas")
    settlement = assess_merchant_candidate("Plazo de acreditacion del reintegro")
    app_notice = assess_merchant_candidate("Notificaciones en la aplicacion movil del banco")
    repeated_heading = assess_merchant_candidate("Ppprrrooommmoooccciiiooonnneeesss")
    single_letter = assess_merchant_candidate("P")
    corporate = assess_merchant_candidate("Ueno Bank S A")
    temporal = assess_merchant_candidate("Exclusivamente Los Dias Jueves")
    legal_series = assess_merchant_candidate("Las Series A Y B")
    payment_label = assess_merchant_candidate("Medios De Pago Habilitados")
    promo_heading = assess_merchant_candidate("Disfruta Tus Rubros Favoritos En Cuotas")
    generic_merchant = assess_merchant_candidate("Comercios Beneficio")
    card_scope = assess_merchant_candidate("Mastercard Debit")

    assert not generic.is_valid
    assert not rubric.is_valid
    assert not disclaimer.is_valid
    assert not cta.is_valid
    assert not helper.is_valid
    assert not mechanic.is_valid
    assert not installments.is_valid
    assert not category_fragment.is_valid
    assert not settlement.is_valid
    assert not app_notice.is_valid
    assert not repeated_heading.is_valid
    assert not single_letter.is_valid
    assert not corporate.is_valid
    assert not temporal.is_valid
    assert not legal_series.is_valid
    assert not payment_label.is_valid
    assert not promo_heading.is_valid
    assert not generic_merchant.is_valid
    assert not card_scope.is_valid
