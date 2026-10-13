Add-Type -AssemblyName System.Drawing

$width = 1800
$height = 1300
$bitmap = [System.Drawing.Bitmap]::new($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$graphics.Clear([System.Drawing.Color]::FromArgb(248, 250, 252))

$font = [System.Drawing.Font]::new("Arial", 18, [System.Drawing.FontStyle]::Bold)
$smallFont = [System.Drawing.Font]::new("Arial", 15, [System.Drawing.FontStyle]::Regular)
$nodeBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(235, 242, 255))
$analysisBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(229, 249, 240))
$validationBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 244, 224))
$terminalBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(226, 232, 240))
$textBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(30, 41, 59))
$borderPen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(71, 85, 105), 2)
$arrowPen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(51, 65, 85), 3)
$arrowPen.CustomEndCap = [System.Drawing.Drawing2D.AdjustableArrowCap]::new(6, 7)

$nodes = @{
    start = [System.Drawing.Rectangle]::new(750, 25, 300, 60)
    user_input = [System.Drawing.Rectangle]::new(700, 125, 400, 70)
    parse_input = [System.Drawing.Rectangle]::new(700, 235, 400, 70)
    analysis = [System.Drawing.Rectangle]::new(700, 345, 400, 70)
    logic_analysis = [System.Drawing.Rectangle]::new(700, 455, 400, 70)
    generate_image = [System.Drawing.Rectangle]::new(100, 720, 400, 70)
    design_game_logic = [System.Drawing.Rectangle]::new(700, 600, 400, 70)
    generate_sound = [System.Drawing.Rectangle]::new(1300, 720, 400, 70)
    validate_game = [System.Drawing.Rectangle]::new(700, 720, 400, 70)
    asset_spec = [System.Drawing.Rectangle]::new(700, 830, 400, 70)
    validate_image = [System.Drawing.Rectangle]::new(100, 950, 400, 70)
    validate_sound = [System.Drawing.Rectangle]::new(1300, 950, 400, 70)
    apply_assets = [System.Drawing.Rectangle]::new(700, 1050, 400, 70)
    final_validation = [System.Drawing.Rectangle]::new(700, 1160, 400, 70)
    end = [System.Drawing.Rectangle]::new(1170, 1160, 240, 70)
}

function TopCenter($rect) { [System.Drawing.Point]::new($rect.X + ($rect.Width / 2), $rect.Y) }
function BottomCenter($rect) { [System.Drawing.Point]::new($rect.X + ($rect.Width / 2), $rect.Bottom) }
function LeftCenter($rect) { [System.Drawing.Point]::new($rect.X, $rect.Y + ($rect.Height / 2)) }
function RightCenter($rect) { [System.Drawing.Point]::new($rect.Right, $rect.Y + ($rect.Height / 2)) }
function Arrow($from, $to) { $graphics.DrawLine($arrowPen, $from, $to) }
function Node($rect, $label, $brush) {
    $graphics.FillRectangle($brush, $rect)
    $graphics.DrawRectangle($borderPen, $rect)
    $format = [System.Drawing.StringFormat]::new()
    $format.Alignment = [System.Drawing.StringAlignment]::Center
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    $textArea = [System.Drawing.RectangleF]::new(
        [single]$rect.X,
        [single]$rect.Y,
        [single]$rect.Width,
        [single]$rect.Height
    )
    $graphics.DrawString($label, $font, $textBrush, $textArea, $format)
    $format.Dispose()
}

Arrow (BottomCenter $nodes.start) (TopCenter $nodes.user_input)
Arrow (BottomCenter $nodes.user_input) (TopCenter $nodes.parse_input)
Arrow (BottomCenter $nodes.parse_input) (TopCenter $nodes.analysis)
Arrow (BottomCenter $nodes.analysis) (TopCenter $nodes.logic_analysis)
Arrow (BottomCenter $nodes.logic_analysis) (TopCenter $nodes.design_game_logic)
Arrow (BottomCenter $nodes.design_game_logic) (TopCenter $nodes.generate_image)
Arrow (BottomCenter $nodes.design_game_logic) (TopCenter $nodes.generate_sound)
Arrow (BottomCenter $nodes.design_game_logic) (TopCenter $nodes.validate_game)
Arrow (BottomCenter $nodes.validate_game) (TopCenter $nodes.asset_spec)
Arrow (BottomCenter $nodes.generate_image) (TopCenter $nodes.validate_image)
Arrow (LeftCenter $nodes.asset_spec) (TopCenter $nodes.validate_image)
Arrow (BottomCenter $nodes.generate_sound) (TopCenter $nodes.validate_sound)
Arrow (RightCenter $nodes.asset_spec) (TopCenter $nodes.validate_sound)
Arrow (BottomCenter $nodes.validate_image) (TopCenter $nodes.apply_assets)
Arrow (BottomCenter $nodes.validate_sound) (TopCenter $nodes.apply_assets)
Arrow (BottomCenter $nodes.apply_assets) (TopCenter $nodes.final_validation)
Arrow (RightCenter $nodes.final_validation) (LeftCenter $nodes.end)

Node $nodes.start "START" $terminalBrush
Node $nodes.user_input "user_input" $nodeBrush
Node $nodes.parse_input "parse_input" $nodeBrush
Node $nodes.analysis "analysis" $analysisBrush
Node $nodes.logic_analysis "logic_analysis" $analysisBrush
Node $nodes.generate_image "generate_image" $nodeBrush
Node $nodes.design_game_logic "design_game_logic" $nodeBrush
Node $nodes.generate_sound "generate_sound" $nodeBrush
Node $nodes.validate_game "validate_game" $validationBrush
Node $nodes.asset_spec "create_asset_validation_spec" $validationBrush
Node $nodes.validate_image "validate_image" $validationBrush
Node $nodes.validate_sound "validate_sound" $validationBrush
Node $nodes.apply_assets "apply_assets_to_game" $nodeBrush
Node $nodes.final_validation "final_validation" $validationBrush
Node $nodes.end "END" $terminalBrush

$graphics.DrawString("MainFlowChart contract 3.0.0", $smallFont, $textBrush, 20, 1255)
$target = Join-Path $PSScriptRoot "..\docs\assets\langgraph_flow.png"
$bitmap.Save($target, [System.Drawing.Imaging.ImageFormat]::Png)

$font.Dispose()
$smallFont.Dispose()
$nodeBrush.Dispose()
$analysisBrush.Dispose()
$validationBrush.Dispose()
$terminalBrush.Dispose()
$textBrush.Dispose()
$borderPen.Dispose()
$arrowPen.Dispose()
$graphics.Dispose()
$bitmap.Dispose()
