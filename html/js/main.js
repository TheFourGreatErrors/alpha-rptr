$.ajaxSetup({ cache: false });

backtest = {}

var chart = LightweightCharts.createChart(document.getElementById("chart"), {
    width: 1000,
    height: 350,
    title: "Alpha RPTR",
    timeScale: {
    timeVisible: true,
    secondsVisible: true,
    minBarSpacing: 0.001
    },
    rightPriceScale: {
    visible: true
    },
    leftPriceScale: {
    visible: true,
    //invertScale: true
    },
});   

candleSeries = chart.addCandlestickSeries({
    upColor: 'rgb(38,166,154)',
    downColor: 'rgb(255,82,82)',
    wickUpColor: 'rgb(38,166,154)',
    wickDownColor: 'rgb(255,82,82)',
    borderVisible: false,
});

equity_chart_series = chart.addAreaSeries({
    //title: "Equity",
    topColor: 'rgba(46, 139, 87, 0.1)',
    bottomColor: 'rgba(46, 139, 87, 0)',
    lineColor: 'rgba(46, 139, 87, 1)',
    lineWidth: 0.5,
    priceScaleId: 'left',
    visible: true
})

drawdown_chart_series = chart.addAreaSeries({
    //title: "DD%",
    topColor: 'rgba(255, 82, 82, 0.1)',
    bottomColor: 'rgba(255, 82, 82, 0)',
    lineColor: 'rgba(255, 82, 82, 1)',
    lineWidth: 0.5,
    priceScaleId: 'left',
    visible: false
})

chart.subscribeCrosshairMove((param) => {
    if (param.time) 
    {
        const price = param.seriesPrices.get(candleSeries);

        if ( price.open < price.close)
        color = "seagreen"
        else
        color = "red"

        $("#chart_title").html('<span style="color: '+color+'">O: '+price.open+'</span> <span style="color: seagreen">H: '+price.high+'</span> <span style="color: red;">L: '+price.low+'</span> <span style="color: '+color+'">C: '+price.close+'</span>');
    }
    else 
    {
        $("#chart_title").html('alpha rptr');
    }
});

$('input[type=radio][name=ed_toggle]').change(function() {
    if (this.value == 'equity') {
        equity_chart_series.applyOptions({visible: true})
        drawdown_chart_series.applyOptions({visible: false})
    }
    else if (this.value == 'drawdown') {
        equity_chart_series.applyOptions({visible: false})
        drawdown_chart_series.applyOptions({visible: true})
    }
});

$('.button.code').click(function(event) {
    $.featherlight('<pre class="source_code"><code id="strategy_code" class="language-python">'+backtest.strategy_code+'</code></pre>', { variant: "srcmodal" }); 
    Prism.highlightElement(document.getElementById('strategy_code'));
    return false;
});

$('.button.fitchart').click(function(){
    chart.timeScale().fitContent()
})

$(document).ready(function(){

    var title = get_title()

    if (title)
    {
        load_backtest(title)
    }
    else
    {
        $.get( "/data/data.csv", function( data ) {
            
            chart_data = $.csv.toObjects(data);
            time_index = Object()
            time_length = chart_data.length
        
            for (var i=0; i<chart_data.length; i++)
            {
                var time = new Date(chart_data[i]["time"]).getTime()/1000
                chart_data[i]["time"] = time
                time_index[time] = i 
            }
        
            backtest.chart_data = chart_data
            load_chart(chart_data);
            get_load_trades(chart_data);  
            get_strategy_code()    
        
        });  
    } 
})

$('.button.save').click(function(event){
    var form = `
    <div class="save_form">
        <input class="save_title" type="text" placeholder="Name..."/>
        <button class="save_button"><span style="font-size: smaller">&#128190;</span> Save</button>
    </div>
    `;
    $.featherlight(form, {variant: "save_modal"})  
    $(".save_modal .save_title").focus()  
})

$('body').on("click", ".save_form .save_button", {}, function(event){

    var title = $(".save_form .save_title").val().trim()

    if (title.length > 0){

        backtest.saved = typeof backtest.saved == "undefined" ? moment().format("YYYY-MM-DD") 
                                    : backtest.saved

        $.post("/cgi-bin/db.py?key="+title, JSON.stringify(backtest), function(data){

            if(data.result == "success")
            {
                $.get( "/cgi-bin/db.py?key=library", function( data ) {
            
                    library = data.result !== 'not-found' ? JSON.parse(data.library) : {}
            
                    var meta = Object.assign({}, backtest)
                    delete meta.chart_data 
                    delete meta.order_data 
                    delete meta.strategy_code
            
                    library[title] = meta
            
                    $.post("/cgi-bin/db.py?key=library", JSON.stringify(library), function(data){

                        if(data.result == 'success')
                        {
                            $(".header .title span").html(title)
                            set_title(title)
                            $.featherlight.close()
                        }
                        else modal_alert("Error", title+" could not be saved to Library! Try Again!")    
                    })
                }) 
            }
            else modal_alert("Error", title+" could not be saved!")           
        })       
    }
    else modal_alert("Error", "Please provide a valid name to the Backtest") 
})
  
/*-------------------------*/

function modal_alert(title, content)
{    
    var html = `
    <div class="message">
        <h3>{title}</h3>
        <p>{content}</p>
    </div>
    `;
    html = html.replace("{title}", title).replace("{content}", content)
    $.featherlight(html, {variant: "alert"})    
}

function modal_dialog(title, content, button, callback)
{    
    var id = Date.now()
    var html = `
    <div class="message" id="{id}">
        <h3>{title}</h3>
        <p>{content}</p>
        <div class=buttons-cont">
            <button class="confirm">{button}</button>
            <button class="cancel">Cancel</button>
        </div>
    </div>
    `;
    html = html.replace("{id}", id)
                .replace("{title}", title)
                .replace("{content}", content)
                .replace("{button}", button)
    $.featherlight(html, {variant: "dialog"})   
    
    $(".dialog #"+id+" .confirm").click(function(event){
        callback();
        $.featherlight.close()
    })

    $(".dialog #"+id+" .cancel").click(function(event){
        $.featherlight.close()
    })
}

$(".library").click(function(event){

    $.get( "/cgi-bin/db.py?key=library", function( data ) {

        if(data.result !== 'not-found')
        {   
            library = JSON.parse(data["library"])            
        }
        else modal_alert("Error", "Library is empty")

        library_table =  Array()

        for (const test in library) {
            var meta = library[test]
            var test_link = '<a class="test_link underline" target="_blank" href="' + get_backtest_link(test )+ '" onclick="load_backtest_link(event,\'' + test + '\')">' + '♈ ' + test + '</a>'
            var delete_link = '<a class="delete_link" title="'+test+'" href="#">⛔</a>'
            library_table.push([test_link, meta.cagr, meta.max_dd, meta.period, meta.start_date, meta.end_date, meta.saved, delete_link])
        }

        var html = `
        <div class="library_cont">
            <table id="backtests" class="display "></table>
        </div>
        `;
        //html = html.replace("{title}", title).replace("{content}", content)
        $.featherlight(html, {variant: "library_modal"})  

        $('#backtests').DataTable( {
            data: library_table,
            // searching: false,
            columns: [
                { title: 'Name' , width: '49%', className: "left-aligned-cell" },
                { title: 'CAGR%' },
                { title: 'MaxDD%' },
                { title: 'Period' },
                { title: 'Start' },
                { title: 'End' },
                { title: 'Saved' },
                { title: ' ', searchable: false, orderable: false }
            ]
        });
    })
})

function load_backtest_link(event, title)
{    
    load_backtest(title)
    $.featherlight.close()
    event.preventDefault()
}

$('body').on( 'click', '#backtests .delete_link', function () {

    var table = $('#backtests').DataTable();
    var title = $(this).attr("title")
    var element = this

    var message = "Do you really want to delete <b>"+title+"</b> from Library?"

    modal_dialog("Confirm Delete", message, "Delete", function(){

        $.get( "/cgi-bin/db.py?key=library", function( data ) {
                
            library = data.result !== 'not-found' ? JSON.parse(data.library) : {}

            if (typeof library[title] !== "undefined")
            {
                delete library[title]

                $.post("/cgi-bin/db.py?key=library", JSON.stringify(library), function(data){

                    if(data.result !== 'success')
                    modal_alert("Error", title+" could not be removed from Library! Try Again!")    
                })
            }             
            else modal_alert("Error", title+" is not in Library!")        
        }) 
        
        $.get( "/cgi-bin/db.py?do=delete&key="+title, function( data ) {
            
            if(data.result == 'success'){
                table
                    .row( $(element).parents('tr') )
                    .remove()
                    .draw();
            }
            
        });
    })    

    return false
});

function load_backtest(title)
{
    $.get( "/cgi-bin/db.py?key="+title, function( data ) {

        if(data.result !== 'not-found')
        {   
            backtest = JSON.parse(data[title])
            $(".header .title span").html(title)
            set_title(title)
            load_data(backtest.chart_data, backtest.order_data)
            
            chart.timeScale().fitContent()
        }
        else modal_alert("Error", "Backtest not found!")
    })
}

function load_data(chart_data, order_data)
{
    if ( $('#trades').children().length > 0 ) {
        $('#trades').DataTable().destroy()
        $('#trades').html('')
    }

    time_index = Object()
    time_length = chart_data.length

    for (var i=0; i<chart_data.length; i++)
    {
        time_index[chart_data[i]["time"]] = i
    }

    load_chart(chart_data)
    load_trades(chart_data, order_data)
}

/*-------------------------*/

function set_title(title)
{
    var url = new URL(window.location);
    url.searchParams.set('title', title);
    window.history.pushState({}, '', url);
}

function get_title()
{
    var url = new URL(window.location);
    var title = url.searchParams.get('title');

    return title
}

function get_backtest_link(title)
{
    var url = new URL(window.location);
    url.searchParams.set('title', title);
    return url.toString()
}


function load_chart(chart_data){
    candleSeries.setData(chart_data);
}    

function get_load_trades(chart_data){
    
    $.get( "/data/orders.csv", function( data ) {

        order_data = $.csv.toObjects(data);
        backtest.order_data = order_data
        load_trades(chart_data, order_data)

    })
}

function date_link(date)
{
    var time = new Date(date).getTime()/1000
    var chart_position = time_index[time]

    range = chart.timeScale().getVisibleLogicalRange();
    range = (Math.floor(range["to"]) - Math.floor(range["from"]))

    chart_position = chart_position - time_length + range/2
    chart.timeScale().scrollToPosition(chart_position,true)
    chart.priceScale().applyOptions({autoScale: true})
}

function format_number(price, sig_digits){
    price = parseFloat(price)
    return price >= 1 || price <= -1 ? (price % 1 == 0 ? price : price.toFixed(sig_digits)) : price.toPrecision(sig_digits)
}

function load_trades(chart_data, order_data){      

    var drawdown = {};
    var balance = {};

    backtest.start_date = null
    backtest.end_date = null     
    
    backtest.capital = 0
    backtest.nav = 0
    backtest.max_dd = 0

    var markers = [];
    var only_markers = [];

    var trades_table = Array()

    for (var i=0; i<order_data.length; i++){

        //"time,type,price,quantity,av_price,position,pnl,balance\n"

        if(i==0)
        {
            backtest.start_date = moment.utc(order_data[i]["time"])
            backtest.capital = parseInt(order_data[i]["balance"])
        }

        if(i==order_data.length-1)
        {
            backtest.end_date = moment.utc(order_data[i]["time"])
            backtest.nav = parseInt(order_data[i]["balance"])
        }

        var order_date = moment.utc(order_data[i]["time"]).format("YYYY-MM-DD HH:mm")        
        order_date = '<a class="chart_link underline" href="javascript:date_link(\''+order_data[i]["time"]+'\')">📈 '+order_date+'</a>'

        var type = '<span class="'+order_data[i]["type"]+'">'+order_data[i]["id"]+'</span>'
        
        var number_formatter = Intl.NumberFormat('en-US', {
            notation: "compact",
            maximumSignificantDigits: 6
        });

        var quantity_formatted = format_number(order_data[i]["quantity"], 2)
        quantity_formatted = isNaN(quantity_formatted) ? '-' : (Math.abs(quantity_formatted) > 10**6 ? number_formatter.format(quantity_formatted) : quantity_formatted)
        quantity_formatted = '<div title="'+order_data[i]["quantity"]+'">'+quantity_formatted+'</div>'

        var position_formatted = format_number(order_data[i]["position"], 2)
        position_formatted = isNaN(position_formatted) ? '-' : (Math.abs(position_formatted) > 10**6 ? number_formatter.format(position_formatted) : position_formatted)
        position_formatted = '<div title="'+order_data[i]["position"]+'">'+position_formatted+'</div>'

        var pnl_formatted = parseFloat(order_data[i]["pnl"])
        pnl_formatted = isNaN(pnl_formatted) ? '-' : (Math.abs(pnl_formatted) > 10**6 ? number_formatter.format(pnl_formatted) : pnl_formatted)
        pnl_formatted = '<div title="'+order_data[i]["pnl"]+'">'+pnl_formatted+'</div>'

        var balance_formatted = order_data[i]["balance"]
        balance_formatted = isNaN(balance_formatted) ? '-' : (Math.abs(balance_formatted) > 10**6 ? number_formatter.format(balance_formatted) : balance_formatted)
        balance_formatted = '<div title="'+order_data[i]["balance"]+'">'+balance_formatted+'</div>'          
        
        var price_formatted = format_number(order_data[i]["price"], 2)
        var av_price_formatted = format_number(order_data[i]["av_price"], 2)
        
        trades_table.push([order_date, type, price_formatted, quantity_formatted, av_price_formatted, position_formatted, pnl_formatted, balance_formatted,order_data[i]["drawdown"]])

        var time = new Date(order_data[i]["time"]).getTime()/1000

        //drawdown.push({ time: time, value: parseInt(order_data[i]["drawdown"]) });
        drawdown[time] = parseFloat(order_data[i]["drawdown"]);
        balance[time] = parseFloat(order_data[i]["balance"]);

        backtest.max_dd = drawdown[time] > backtest.max_dd ? drawdown[time] : backtest.max_dd

        if(order_data[i]["type"] == 'BUY')
        {
            markers.push({ time: time, position: 'belowBar', color: '#0345a1', shape: 'arrowUp', text: 'Buy @ ' + price_formatted + ' Qty: ' + order_data[i]["quantity"] });
            only_markers.push({ time: time, position: 'belowBar', color: '#0345a1', shape: 'arrowUp' });
        }        
        else  
        {
            markers.push({ time: time, position: 'aboveBar', color: "#870a01", shape: 'arrowDown', text: 'Sell @ ' + price_formatted + ' Qty: ' + order_data[i]["quantity"] });
            only_markers.push({ time: time, position: 'aboveBar', color: "#870a01", shape: 'arrowDown'});
        }          
    }

    backtest.period = backtest.end_date.diff(backtest.start_date, 'days')
    backtest.start_date = backtest.start_date.format("YYYY-MM-DD")    
    backtest.end_date = backtest.end_date.format("YYYY-MM-DD")    
    backtest.cagr = Math.round(((backtest.nav/backtest.capital)**(365/backtest.period)-1)*100)

    $(".props").html("CAGR: "+backtest.cagr+"% &bull; MaxDD: "+backtest.max_dd+"% &bull; "+backtest.period+" days &bull; "+backtest.start_date+" - "+backtest.end_date)

    var drawdown_series = [];
    var balance_series = [];

    var last_drawdown = 0
    var last_balance = 0

    for (var i=0; i<chart_data.length; i++){

        let time = chart_data[i]["time"];

        if ( time in drawdown)
        {
            drawdown_series.push({time: time, value: drawdown[time]})
            last_drawdown = drawdown[time]
        }
        else 
        drawdown_series.push({time: time, value: last_drawdown})

        if ( time in balance)
        {
            balance_series.push({time: time, value: balance[time]})
            last_balance = balance[time]
        }
        else 
        balance_series.push({time: time, value: last_balance})
    }

    equity_chart_series.setData(balance_series);      
    drawdown_chart_series.setData(drawdown_series);      

    candleSeries.setMarkers(markers);

    function onVisibleLogicalRangeChanged(range) {
        console.log(range);
        start = parseInt(range["from"]);
        end = parseInt(range["to"]);

        if(end-start > 500)
        candleSeries.setMarkers([]);
        else if (end-start > 200)
        candleSeries.setMarkers(only_markers);
        else
        candleSeries.setMarkers(markers);
    }

    chart.timeScale().subscribeVisibleLogicalRangeChange(onVisibleLogicalRangeChanged);
    
    $('#trades').DataTable( {
        data: trades_table,
        // searching: false,
        columns: [
            { title: 'Date' },
            { title: 'Type' },
            { title: 'Price' },
            { title: 'Quantity' },
            { title: 'Av. Price' },
            { title: 'Position' },
            { title: 'PnL' },
            { title: 'Balance' },
            { title: 'Drawdown' }
        ]
    });
}   

function get_strategy_code()
{
    $.get( "/data/strategy.py", function( data ) {
        backtest.strategy_code = data    
    });   
}
